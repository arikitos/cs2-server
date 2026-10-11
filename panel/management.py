"""Persistent users, permanent bans/admins, public address and configuration backups."""
import copy
import ipaddress
import json
import os
import re
import secrets
import time
import urllib.request
from pathlib import Path

from .core import Problem, atomic_json, load_json

MODES_ROOT = Path(__file__).resolve().parent.parent / 'runtime/modes'
MODES = ('matchzy', 'retakes', 'deathmatch')


def steam_id(value):
    value = str(value)
    if not re.fullmatch(r'\d{17}', value) or not 76561197960265728 <= int(value) <= 76561202255233023:
        raise Problem('A validated individual SteamID64 is required')
    return value


class Management:
    def __init__(self, controller, control=None, telemetry=None):
        self.controller = controller
        self.control = Path(control or os.environ.get('CS2_CONTROL_DIR', '/control'))
        self.telemetry = Path(telemetry or os.environ.get('CS2_TELEMETRY_DIR', '/telemetry'))
        self.control.mkdir(parents=True, exist_ok=True)
        self.control.chmod(0o750)
        if os.getuid() == 0:
            os.chown(self.control, 0, 1000)
        self.users = load_json(controller.state_dir / 'users.json', {})
        self.address_cache = None
        self.last_lookup = 0
        self.last_history = None
        self.write_policy()

    def write_policy(self):
        c = self.controller
        with c.lock:
            atomic_json(c.state_dir / 'users.json', self.users)
            admins = {identity: {'identity': identity, 'flags': ['@css/root'], 'immunity': 100}
                      for identity, user in self.users.items() if user.get('admin') and not user.get('banned')}
            for name, data in [('admins.json', admins),
                               ('policy.json', {'bans': sorted(identity for identity, user in self.users.items() if user.get('banned'))})]:
                path = self.control / name
                atomic_json(path, data, 0o640)
                if os.getuid() == 0:
                    os.chown(path, 0, 1000)

    def ingest_history(self):
        path = self.telemetry / 'users-seen.json'
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp == self.last_history:
                return
            if stat.st_size > 16 * 1024 * 1024:
                raise Problem('Player history exceeds the supported size')
            history = json.loads(path.read_text())
        except FileNotFoundError:
            return
        if not isinstance(history, dict):
            raise Problem('Invalid player history')
        with self.controller.lock:
            for identity, seen in history.items():
                try:
                    identity = steam_id(identity)
                except Problem:
                    continue
                if not isinstance(seen, dict):
                    continue
                current = self.users.setdefault(identity, {'steamid': identity, 'admin': False, 'banned': False})
                for field in ('name', 'first_seen', 'last_seen', 'visits'):
                    if field in seen:
                        current[field] = seen[field]
            atomic_json(self.controller.state_dir / 'users.json', self.users)
            self.last_history = stamp

    def players(self):
        self.ingest_history()
        info = self.controller.engine.inspect('cs2-local-server')
        if not info or not info['State']['Running']:
            return {'players': [], 'error': None}
        try:
            live = load_json(self.telemetry / 'live.json')
            if not live or time.time() - live.get('updated_at', 0) > 12:
                raise Problem('Waiting for the server management plugin')
            result = []
            for player in live.get('players', []):
                player = dict(player)
                identity = player.get('steamid')
                if identity:
                    steam_id(identity)
                user = self.users.get(identity, {})
                player.update(admin=bool(user.get('admin')), banned=bool(user.get('banned')))
                result.append(player)
            return {'players': result, 'error': None}
        except (Problem, ValueError, OSError) as error:
            return {'players': [], 'error': str(error)}

    def registry(self):
        self.ingest_history()
        with self.controller.lock:
            return {'users': sorted(copy.deepcopy(list(self.users.values())), key=lambda u: u.get('last_seen', 0), reverse=True)}

    def user_action(self, data):
        c = self.controller
        identity = steam_id(data.get('steamid', ''))
        action = data.get('action')
        if action not in {'kick', 'ban', 'unban', 'admin', 'remove_admin'}:
            raise Problem('Unknown player action')
        if not c.operation_lock.acquire(blocking=False):
            raise Problem('Wait for the current server operation', 409)
        try:
            self.ingest_history()
            with c.lock:
                if identity not in self.users:
                    raise Problem('This SteamID has not joined this server', 404)
                info = c.engine.inspect('cs2-local-server')
                running = bool(info and info['State']['Running'])
                if action == 'kick':
                    if not running:
                        raise Problem('Server is not running', 409)
                    output = c.rcon_command('css_local_kick ' + identity)
                    if 'CS2LOCAL_NOT_FOUND' in output:
                        raise Problem('The player has already left the server', 409)
                    if 'CS2LOCAL_OK' not in output:
                        raise Problem('The management plugin did not acknowledge the kick', 503)
                else:
                    user = self.users[identity]
                    if action in {'ban', 'unban'}:
                        user['banned'] = action == 'ban'
                        user['banned_at'] = time.time() if action == 'ban' else None
                    else:
                        user['admin'] = action == 'admin'
                    self.write_policy()
                    # The plugin also polls this durable policy while the panel is closed.
                    if running:
                        try:
                            output = c.rcon_command('css_local_reload')
                            if 'CS2LOCAL_OK' not in output:
                                raise Problem('Management plugin is still loading')
                        except Exception as error:
                            self.audit(action, identity, 'saved; pending game synchronization')
                            return {'saved': True, 'pending': True, 'message': 'Saved. The server plugin will apply this policy when available.'}
                self.audit(action, identity)
                return {'saved': True, 'pending': False}
        finally:
            c.operation_lock.release()

    def public_address(self, force=False):
        now = time.monotonic()
        if not force and self.address_cache and now - self.last_lookup < 600:
            return dict(self.address_cache)
        last_error = 'Public IP lookup is unavailable'
        for url in ('https://checkip.amazonaws.com/', 'https://api.ipify.org/'):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'CS2-Local/2'})
                with urllib.request.urlopen(request, timeout=3) as response:
                    value = response.read(100).decode().strip()
                address = ipaddress.ip_address(value)
                if address.version != 4 or not address.is_global:
                    raise ValueError('The detected address is not a public IPv4 address')
                self.address_cache = {'ip': str(address), 'port': 27015, 'address': str(address) + ':27015', 'error': None}
                self.last_lookup = now
                return dict(self.address_cache)
            except Exception as error:
                last_error = str(error)
        return {'ip': None, 'port': 27015, 'address': None, 'error': 'Could not detect your public IP. Retry the lookup.',
                'last_known_address': (self.address_cache or {}).get('address')}

    def modes(self):
        rows = []
        for mode in MODES:
            manifest = load_json(MODES_ROOT / mode / 'mode.json')
            rows.append({'id': mode, 'label': manifest['label'], 'actions': manifest.get('actions', [])})
        return {'modes': rows}

    def mode_action(self, data):
        mode = self.controller.config['game_mode']
        actions = load_json(MODES_ROOT / mode / 'mode.json').get('actions', [])
        action = next((a for a in actions if a['key'] == data.get('key')), None)
        if not action:
            raise Problem('This action is unavailable in the selected mode')
        args = str(data.get('args', '')).strip()
        if len(args) > 128 or any(c in args for c in ';\n\r'):
            raise Problem('Invalid command arguments')
        if args and not action.get('arg_hint'):
            raise Problem('This action does not accept arguments')
        result = self.controller.command(action['cmd'] + (' ' + args if args else ''))
        self.audit('mode_action', action['key'])
        return {'output': result}

    def audit(self, action, target='', outcome='ok'):
        with self.controller.lock:
            path = self.controller.state_dir / 'audit.jsonl'
            if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
                os.replace(path, path.with_name('audit.previous.jsonl'))
            with path.open('a') as stream:
                stream.write(json.dumps({'at': time.time(), 'action': action, 'target': target, 'outcome': self.controller.redact(outcome)}) + '\n')
            path.chmod(0o600)

    def audit_rows(self):
        path = self.controller.state_dir / 'audit.jsonl'
        return {'entries': [json.loads(line) for line in path.read_text().splitlines()[-100:]][::-1] if path.exists() else []}

    def backup(self, reason='manual'):
        with self.controller.lock:
            self.ingest_history()
            identifier = time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4)
            value = {'schema': 1, 'created_at': time.time(), 'reason': reason,
                     'config': copy.deepcopy(self.controller.config), 'users': copy.deepcopy(self.users)}
            atomic_json(self.controller.state_dir / 'backups' / (identifier + '.json'), value)
            self.audit('backup', identifier)
            return identifier

    def backups(self):
        result = []
        for path in sorted((self.controller.state_dir / 'backups').glob('*.json'), reverse=True):
            data = load_json(path)
            result.append({'id': path.stem, 'created_at': data['created_at'], 'reason': data['reason']})
        return {'backups': result}

    def read_backup(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'\d{8}-\d{6}-[0-9a-f]{8}', identifier):
            raise Problem('Invalid backup identifier')
        path = self.controller.state_dir / 'backups' / (identifier + '.json')
        data = load_json(path)
        if not data or data.get('schema') != 1 or not isinstance(data.get('users'), dict):
            raise Problem('Backup is missing or invalid', 404)
        return data
