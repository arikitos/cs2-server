import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import struct
import threading
import time
from collections import deque
from pathlib import Path

from .docker_engine import DockerEngine, EngineError

IMAGE = 'cs2-local-runtime:2'
SERVER = 'cs2-local-server'
JOB = 'cs2-local-job'
LABELS = {'io.cs2-local.managed': 'true', 'io.cs2-local.runtime': '2'}
BUSY = {'building', 'installing', 'checking', 'updating', 'starting', 'configuring', 'repairing', 'validating', 'restoring'}

class Problem(Exception):
    def __init__(self, message, status=400, **details):
        super().__init__(message)
        self.status = status
        self.details = details

def atomic_json(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'w') as file:
        json.dump(value, file)
    temporary.chmod(mode)
    os.replace(temporary, path)

def load_json(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()

def verify_password(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)

def config_from(data, existing=None):
    existing = existing or {}
    def text(key, maximum=128, default=''):
        value = str(data.get(key, existing.get(key, default)))
        if key != 'join_password':
            value = value.strip()
        if len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise Problem(f'Invalid {key}')
        return value
    def number(key, low, high, default):
        try:
            raw = data.get(key, existing.get(key, default))
            if isinstance(raw, bool):
                raise ValueError()
            value = int(raw)
        except (ValueError, TypeError):
            raise Problem(f'Invalid {key}')
        if not low <= value <= high:
            raise Problem(f'{key} must be between {low} and {high}')
        return value
    name = text('server_name', 64, 'My CS2 Server')
    if not name:
        raise Problem('Server name is required')
    mode = str(data.get('network_mode', 'internet'))
    if mode != 'internet':
        raise Problem('This server uses Internet access')
    gslt = text('gslt', 32)
    if gslt and not re.fullmatch(r'[0-9a-fA-F]{32}', gslt):
        raise Problem('GSLT must contain 32 hexadecimal characters')
    if not gslt:
        raise Problem('Internet mode requires a Game Server Login Token (GSLT)')
    game_map = text('map', 40, 'de_dust2')
    if game_map not in {'de_dust2', 'de_mirage', 'de_inferno', 'de_nuke', 'de_ancient', 'de_anubis', 'de_overpass'}:
        raise Problem('Choose a supported installation map')
    if number('port', 27015, 27015, 27015) != 27015:
        raise Problem('Game port is fixed at 27015')
    game_mode = text('game_mode', 32, 'matchzy')
    if game_mode not in {'matchzy', 'retakes', 'deathmatch'}:
        raise Problem('Choose MatchZy, Retakes or Official Deathmatch')
    return {'server_name': name, 'network_mode': mode, 'gslt': gslt,
            'port': 27015, 'max_players': number('max_players', 2, 64, 10), 'game_mode': game_mode,
            'map': game_map, 'join_password': text('join_password', 64),
            'rcon_password': existing.get('rcon_password') or secrets.token_urlsafe(32)}

def installed_build(manifest):
    match = re.search(r'"buildid"\s*"(\d+)"', manifest)
    return match.group(1) if match else None

def public_build(output):
    # Parse Valve KeyValues structurally so beta/depot build IDs cannot win a regex match.
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', output)
    flat = [quoted or brace for quoted, brace in tokens]
    def parse(index):
        result = {}
        while index < len(flat) and flat[index] != '}':
            key = flat[index]
            index += 1
            if index >= len(flat):
                break
            if flat[index] == '{':
                value, index = parse(index + 1)
            else:
                value = flat[index]
                index += 1
            result[key] = value
        return result, index + 1
    try:
        start = next(i for i in range(len(flat) - 1) if flat[i] == '730' and flat[i + 1] == '{')
        tree, _ = parse(start + 2)
        build = tree['depots']['branches']['public']['buildid']
        return build if str(build).isdigit() else None
    except (StopIteration, KeyError, TypeError):
        return None

class Controller:
    def __init__(self, state='/state', config='/config', engine=None, control=None, telemetry=None):
        self.state_dir, self.config_dir = Path(state), Path(config)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine or DockerEngine()
        self.network = os.environ.get('CS2_NETWORK', 'cs2-local-network')
        self.game_volume = os.environ.get('CS2_GAME_VOLUME', 'cs2-local-game')
        self.config_volume = os.environ.get('CS2_CONFIG_VOLUME', 'cs2-local-config')
        self.control_volume = os.environ.get('CS2_CONTROL_VOLUME', 'cs2-local-control')
        self.telemetry_volume = os.environ.get('CS2_TELEMETRY_VOLUME', 'cs2-local-telemetry')
        self.lock = threading.RLock()
        self.operation_lock = threading.Lock()
        self.sessions = {}
        self.failures = {}
        self.logs = deque(maxlen=500)
        self.account = load_json(self.state_dir / 'account.json')
        self.config = load_json(self.config_dir / 'server.json')
        if self.config:
            self.config.setdefault('game_mode', 'matchzy')
        self.bootstrap = load_json(self.state_dir / 'bootstrap.json')
        self.job = load_json(self.state_dir / 'job.json', {'stage': 'idle', 'installed': False})
        if self.job['stage'] in BUSY:
            self.set_stage('failed', 'Panel restarted during an operation. Retry to resume the persistent download.')
        if not self.account and not self.bootstrap:
            self.bootstrap = secrets.token_urlsafe(32)
            atomic_json(self.state_dir / 'bootstrap.json', self.bootstrap)
        if not self.account:
            print('First-time setup token: ' + self.bootstrap, flush=True)
        from .management import Management
        default_root = self.state_dir.parent if str(state) != '/state' else Path('/')
        self.management = Management(self, control or os.environ.get('CS2_CONTROL_DIR', default_root / 'control'),
                                      telemetry or os.environ.get('CS2_TELEMETRY_DIR', default_root / 'telemetry'))

    def redact(self, value):
        value = str(value)
        for secret in [self.bootstrap] + [self.config.get(k) for k in ('gslt', 'rcon_password', 'join_password') if self.config]:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return re.sub(r'(?i)\b(rcon_password|sv_password|sv_setsteamaccount)\s+(?:"[^"\n]*"|[^\s\n]+)',
                      r'\1 [REDACTED]', value)

    def log(self, value):
        with self.lock:
            self.logs.extend(self.redact(value).strip().splitlines())

    def set_stage(self, stage, error=None, **extra):
        with self.lock:
            self.job.update(stage=stage, error=self.redact(error) if error else None, **extra)
            atomic_json(self.state_dir / 'job.json', self.job)

    def create_account(self, data):
        with self.lock:
            if self.account:
                raise Problem('Setup has already been completed', 409)
            if not hmac.compare_digest(str(data.get('setup_token', '')), self.bootstrap):
                raise Problem('Invalid setup token. See docker compose logs panel.', 403)
            username, password = data.get('username', ''), data.get('password', '')
            if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{3,32}', username):
                raise Problem('Username must contain 3-32 letters, numbers, dots, dashes or underscores')
            if not isinstance(password, str) or not 12 <= len(password) <= 128:
                raise Problem('Panel password must contain 12-128 characters')
            self.account = {'username': username, 'password_hash': password_hash(password)}
            atomic_json(self.state_dir / 'account.json', self.account)
            (self.state_dir / 'bootstrap.json').unlink(missing_ok=True)
            return self.new_session()

    def login(self, data, address):
        with self.lock:
            recent = [t for t in self.failures.get(address, []) if time.monotonic() - t < 60]
            if len(recent) >= 5:
                raise Problem('Too many login attempts. Try again in one minute.', 429)
            password = data.get('password', '')
            if not isinstance(password, str) or len(password) > 128:
                raise Problem('Invalid credentials', 401)
            if not self.account or data.get('username') != self.account['username'] or not verify_password(password, self.account['password_hash']):
                self.failures[address] = recent + [time.monotonic()]
                raise Problem('Invalid credentials', 401)
            self.failures.pop(address, None)
            return self.new_session()

    def new_session(self):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.sessions[token] = {'csrf': csrf, 'expires': time.time() + 8 * 3600}
        return token, csrf

    def authorize(self, token, csrf=None):
        with self.lock:
            session = self.sessions.get(token)
            if not session or session['expires'] < time.time():
                self.sessions.pop(token, None)
                raise Problem('Please sign in', 401)
            if csrf is not None and not hmac.compare_digest(csrf, session['csrf']):
                raise Problem('Invalid CSRF token', 403)
            return session

    def write_config(self):
        path = self.config_dir / 'server.json'
        atomic_json(path, self.config, 0o640)
        if os.getuid() == 0:
            self.config_dir.chmod(0o750)
            os.chown(self.config_dir, 0, 1000)
            os.chown(path, 0, 1000)

    def preflight(self):
        info = self.engine.request('GET', '/info')
        architecture = info.get('Architecture', '')
        return {'docker': True, 'architecture': architecture, 'memory_gb': round(info.get('MemTotal', 0) / 2**30, 1),
                'supported': info.get('OSType') == 'linux' and architecture in {'x86_64', 'amd64'}}

    def start_operation(self, operation, data=None):
        if not self.operation_lock.acquire(blocking=False):
            raise Problem('Another operation is running', 409)
        try:
            if operation == 'install':
                if self.job.get('installed'):
                    raise Problem('Server is already installed', 409)
                info = self.preflight()
                if not info['supported']:
                    raise Problem('CS2 requires a Linux x86-64 Docker engine. Use Linux containers on Windows; ARM is not supported.')
                self.config = config_from(data or {})
                self.write_config()
            elif not self.job.get('installed'):
                raise Problem('Install the server first', 409)
            elif operation == 'configure':
                data = {'config': config_from(data or {}, self.config)}
            elif operation == 'restore':
                backup = self.management.read_backup((data or {}).get('id'))
                data = {'backup': backup, 'config': config_from(backup['config'], self.config)}
            elif operation in {'start', 'restart', 'repair', 'validate'}:
                config_from(self.config, self.config)
            self.set_stage('building' if operation == 'install' else 'checking' if operation == 'start' else 'starting')
            thread = threading.Thread(target=self.worker, args=(operation, data or {}), daemon=True)
            thread.start()
        except Exception:
            self.operation_lock.release()
            raise

    def mounts(self, with_config=False):
        mounts = [{'Type': 'volume', 'Source': self.game_volume, 'Target': '/game'}]
        if with_config:
            mounts.append({'Type': 'volume', 'Source': self.config_volume, 'Target': '/config', 'ReadOnly': True})
            mounts.append({'Type': 'volume', 'Source': self.control_volume, 'Target': '/control', 'ReadOnly': True})
            mounts.append({'Type': 'volume', 'Source': self.telemetry_volume, 'Target': '/telemetry'})
        return mounts

    def run_job(self, operation):
        existing = self.engine.inspect(JOB)
        if existing and existing['State']['Running']:
            if existing['Config']['Labels'].get('io.cs2-local.operation') != operation:
                raise Problem('A previous Docker job is still running. Wait for it to finish.', 409)
            self.log('Resuming the existing Docker job.')
        else:
            self.engine.remove(JOB)
            self.engine.request('POST', f'/containers/create?name={JOB}', {
                'Image': IMAGE, 'Cmd': [operation], 'Tty': True,
                'Labels': {**LABELS, 'io.cs2-local.operation': operation},
                'HostConfig': {'Mounts': self.mounts(operation == 'repair'), 'Init': True,
                               'LogConfig': {'Type':'json-file', 'Config':{'max-size':'10m','max-file':'3'}}},
            })
            self.engine.request('POST', f'/containers/{JOB}/start')
        last = ''
        while True:
            output = self.engine.logs(JOB, tail=500)
            if output != last:
                self.log(output[len(last):] if output.startswith(last) else output)
                last = output
            info = self.engine.inspect(JOB)
            if not info['State']['Running']:
                if info['State']['ExitCode'] != 0:
                    raise Problem(f'{operation} failed (exit {info["State"]["ExitCode"]}). See the installation log.')
                return output
            time.sleep(2)

    def manifest(self):
        output = self.run_job('inspect')
        for line in reversed(output.splitlines()):
            try:
                return json.loads(line)
            except ValueError:
                continue
        raise Problem('Could not inspect the game volume')

    def ensure_runtime(self):
        try:
            self.engine.request('GET', '/images/' + IMAGE + '/json')
        except EngineError as error:
            if error.status != 404:
                raise
            self.set_stage('building')
            self.engine.build(Path(__file__).resolve().parent.parent / 'runtime', IMAGE, self.log)

    def create_server(self):
        existing = self.engine.inspect(SERVER)
        if existing:
            if (existing['Config'].get('Labels') or {}).get('io.cs2-local.runtime') == '2':
                return
            if existing['State']['Running']:
                raise Problem('Restart the server to upgrade its plugin runtime', 409)
            self.engine.remove(SERVER)
        port = str(self.config['port'])
        proxy_port = str(self.config['port'] + 1 if self.config['port'] < 65535 else 65534)
        udp_host = '0.0.0.0'
        self.engine.request('POST', f'/containers/create?name={SERVER}', {
            'Image': IMAGE, 'Cmd': ['server'], 'Labels': LABELS,
            'ExposedPorts': {port + '/udp': {}, proxy_port + '/tcp': {}},
            'Healthcheck': {'Test': ['CMD', 'python3', '/opt/cs2/health.py'],
                            'Interval': 10_000_000_000, 'Timeout': 5_000_000_000,
                            'StartPeriod': 90_000_000_000, 'Retries': 6},
            'HostConfig': {'Mounts': self.mounts(True), 'Init': True, 'RestartPolicy': {'Name': 'unless-stopped'},
                           'PortBindings': {port + '/udp': [{'HostIp': udp_host, 'HostPort': port}],
                                            proxy_port + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': port}]},
                           'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '10m', 'max-file': '3'}}},
            'NetworkingConfig': {'EndpointsConfig': {self.network: {'Aliases': ['cs2']}}},
        })

    def launch_server(self):
        self.ensure_runtime()
        self.create_server()
        self.engine.request('POST', f'/containers/{SERVER}/start')
        self.set_stage('starting')
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            info = self.engine.inspect(SERVER)
            health = info['State'].get('Health', {}).get('Status')
            if health == 'healthy':
                try:
                    self.verify_plugins()
                except Exception as error:
                    self.log('Waiting for required plugins: ' + str(error))
                else:
                    self.set_stage('ready', installed=True)
                    self.log('CS2, Metamod, CounterStrikeSharp and the selected mode are ready.')
                    return
            if not info['State']['Running'] or health == 'unhealthy':
                raise Problem('CS2 did not become healthy. Check the server console.')
            time.sleep(3)
        raise Problem('Timed out waiting for CS2 readiness. Check the server console.')

    def rcon_command(self, command):
        proxy_port = self.config['port'] + 1 if self.config['port'] < 65535 else 65534
        return self.redact(rcon('cs2', proxy_port, self.config['rcon_password'], command))

    def verify_plugins(self):
        meta = self.rcon_command('meta list').lower()
        plugins = self.rcon_command('css_plugins list').lower()
        if 'counterstrikesharp' not in meta or 'unknown command' in plugins:
            raise Problem('Metamod/CounterStrikeSharp did not load')
        required = {'matchzy': ['matchzy'], 'retakes': ['retakes', 'retakes allocator', 'instadefuse'], 'deathmatch': []}[self.config['game_mode']]
        normalized = plugins.replace(' ', '')
        if any(name.replace(' ', '') not in normalized for name in required):
            raise Problem('A required mode plugin did not load')
        if 'CS2LOCAL_OK' not in self.rcon_command('css_local_reload'):
            raise Problem('The permanent management plugin did not load')

    def worker(self, operation, data):
        try:
            self.management.audit(operation, outcome='started')
            if operation in {'configure', 'restore'}:
                self.reconfigure(operation, data)
                return
            if operation in {'repair', 'validate'}:
                self.maintenance(operation)
                return
            if operation == 'restart':
                if self.engine.inspect(SERVER):
                    self.engine.request('POST', f'/containers/{SERVER}/stop?t=30')
                operation = 'start'
            if operation == 'install':
                self.engine.volume(self.game_volume)
                existing = self.engine.inspect(JOB)
                resuming = existing and existing['State']['Running'] and existing['Config']['Labels'].get('io.cs2-local.operation') == 'install'
                if not resuming:
                    self.log('Building the Linux runtime and installing SteamCMD (game download follows).')
                    self.engine.build(Path(__file__).resolve().parent.parent / 'runtime', IMAGE, self.log)
                    volume = self.manifest()
                    if volume['free_bytes'] < 80 * 2**30 and not installed_build(volume['manifest']):
                        raise Problem('Allocate at least 80 GiB of free space to Docker before installing CS2.')
                self.set_stage('installing')
                self.run_job('install')
                build = installed_build(self.manifest()['manifest'])
                if not build:
                    raise Problem('SteamCMD completed without an installed build ID')
                self.set_stage('starting', installed=True, installed_build=build, available_build=None)
                self.write_config()
                self.launch_server()
            elif operation == 'start':
                info = self.engine.inspect(SERVER)
                if info and info['State']['Running']:
                    if info['State'].get('Health', {}).get('Status') == 'healthy':
                        self.set_stage('ready')
                    else:
                        self.launch_server()
                    return
                local = installed_build(self.manifest()['manifest'])
                remote = public_build(self.run_job('check'))
                if not local or not remote:
                    raise Problem('Cannot verify the installed/public build. Retry; the server was not started.')
                if local != remote and str(data.get('approved_build', '')) != remote:
                    self.set_stage('update_available', installed_build=local, available_build=remote)
                    return
                if local != remote:
                    self.management.backup('before-update')
                    self.set_stage('updating')
                    self.run_job('update')
                    local = installed_build(self.manifest()['manifest'])
                    if not local or local == self.job.get('installed_build'):
                        raise Problem('Update did not produce a new installed build. Retry the update check.')
                self.set_stage('starting', installed_build=local, available_build=None)
                self.launch_server()
            elif operation == 'stop':
                if self.engine.inspect(SERVER):
                    self.engine.request('POST', f'/containers/{SERVER}/stop?t=30')
                self.set_stage('idle')
            self.management.audit(operation, outcome='completed')
        except Exception as error:
            self.log(str(error))
            self.set_stage('failed', str(error))
            self.management.audit(operation, outcome='failed: ' + str(error))
        finally:
            self.operation_lock.release()

    def reconfigure(self, operation, data):
        import copy
        previous_config, previous_users = copy.deepcopy(self.config), copy.deepcopy(self.management.users)
        info = self.engine.inspect(SERVER)
        running = bool(info and info['State']['Running'])
        self.management.backup('before-' + operation)
        self.set_stage('restoring' if operation == 'restore' else 'configuring')
        if running:
            self.engine.request('POST', f'/containers/{SERVER}/stop?t=30')
        try:
            self.config = data['config']
            self.write_config()
            if operation == 'restore':
                self.management.users = data['backup']['users']
                self.management.write_policy()
            self.engine.remove(SERVER)
            self.ensure_runtime()
            if running:
                self.launch_server()
            else:
                self.set_stage('idle')
            self.management.audit(operation, outcome='completed')
        except Exception as error:
            self.log('Restoring previous settings after failed configuration: ' + str(error))
            self.config = previous_config
            self.management.users = previous_users
            self.write_config()
            self.management.write_policy()
            self.engine.remove(SERVER)
            if running:
                try:
                    self.launch_server()
                except Exception as rollback_error:
                    raise Problem('Configuration failed and the previous server could not start: ' + str(rollback_error)) from error
            raise Problem('Configuration failed; previous settings were restored: ' + str(error)) from error

    def maintenance(self, operation):
        self.management.backup('before-' + operation)
        info = self.engine.inspect(SERVER)
        running = bool(info and info['State']['Running'])
        if running:
            self.engine.request('POST', f'/containers/{SERVER}/stop?t=30')
        self.ensure_runtime()
        self.set_stage('validating' if operation == 'validate' else 'repairing')
        self.run_job(operation)
        if running:
            self.launch_server()
        else:
            self.set_stage('idle')
        self.management.audit(operation, outcome='completed')

    def settings(self):
        if not self.config:
            return {'settings': None}
        # Intentional owner-only settings endpoint; never expose Steam/RCON credentials.
        return {'settings': {k: self.config[k] for k in ('server_name', 'port', 'max_players', 'map', 'game_mode', 'join_password')},
                'has_gslt': bool(self.config.get('gslt'))}

    def metrics(self):
        info = self.engine.inspect(SERVER)
        if not info or not info['State']['Running']:
            return {'cpu_percent': None, 'memory_bytes': None, 'memory_limit': None}
        stats = self.engine.request('GET', f'/containers/{SERVER}/stats?stream=false')
        current, previous = stats.get('cpu_stats', {}), stats.get('precpu_stats', {})
        cpu = current.get('cpu_usage', {}).get('total_usage', 0) - previous.get('cpu_usage', {}).get('total_usage', 0)
        system = current.get('system_cpu_usage', 0) - previous.get('system_cpu_usage', 0)
        cores = current.get('online_cpus') or len(current.get('cpu_usage', {}).get('percpu_usage', [])) or 1
        memory = stats.get('memory_stats', {})
        cache = memory.get('stats', {}).get('inactive_file', memory.get('stats', {}).get('total_inactive_file', 0))
        return {'cpu_percent': round(cpu / system * cores * 100, 1) if system > 0 and cpu >= 0 else None,
                'memory_bytes': max(memory.get('usage', 0) - cache, 0), 'memory_limit': memory.get('limit')}

    def status(self):
        server, engine_error = None, None
        try:
            server = self.engine.inspect(SERVER)
        except Exception as error:
            engine_error = self.redact(error)
        with self.lock:
            config = {k: self.config[k] for k in ('server_name', 'port', 'map', 'max_players', 'network_mode', 'game_mode')} if self.config else None
            return {'job': dict(self.job), 'config': config, 'logs': list(self.logs), 'docker_error': engine_error,
                    'server': {'running': server['State']['Running'], 'health': server['State'].get('Health', {}).get('Status', 'unknown'),
                               'started_at': server['State'].get('StartedAt')} if server else None}

    def command(self, command):
        if not isinstance(command, str) or not 1 <= len(command) <= 1024 or any(ord(c) < 32 for c in command):
            raise Problem('Provide a single RCON command (1-1024 characters)')
        if not self.operation_lock.acquire(blocking=False):
            raise Problem('Wait for the current operation to finish', 409)
        try:
            info = self.engine.inspect(SERVER)
            if not info or not info['State']['Running']:
                raise Problem('Server is not running', 409)
            return self.rcon_command(command)
        finally:
            self.operation_lock.release()

def rcon(host, port, password, command):
    def read_exact(sock, count):
        result = b''
        while len(result) < count:
            chunk = sock.recv(count - len(result))
            if not chunk:
                raise Problem('RCON connection closed')
            result += chunk
        return result
    def receive(sock):
        size = struct.unpack('<i', read_exact(sock, 4))[0]
        if not 10 <= size <= 4 * 1024 * 1024:
            raise Problem('Invalid RCON response')
        packet = read_exact(sock, size)
        return struct.unpack('<ii', packet[:8]) + (packet[8:-2].decode(errors='replace'),)
    def send(sock, request_id, kind, body):
        packet = struct.pack('<ii', request_id, kind) + body.encode() + b'\0\0'
        sock.sendall(struct.pack('<i', len(packet)) + packet)
    with socket.create_connection((host, port), timeout=5) as sock:
        send(sock, 1, 3, password)
        for _ in range(3):
            request_id, kind, _ = receive(sock)
            if request_id == -1:
                raise Problem('RCON authentication failed')
            if kind == 2 and request_id == 1:
                break
        else:
            raise Problem('RCON authentication failed')
        send(sock, 2, 2, command)
        send(sock, 3, 0, '')  # Response marker: collect all packets, including long command output.
        output = []
        for _ in range(128):
            request_id, _, body = receive(sock)
            if request_id == 3:
                return '\n'.join(output)
            if request_id == 2:
                output.append(body)
        raise Problem('RCON response exceeded the packet limit')
