"""Generate a private config and exec CS2; never run SteamCMD on server startup."""
import json
import os
import subprocess
from pathlib import Path

from prepare import prepare

def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'

def main():
    settings = json.loads(Path('/config/server.json').read_text())
    prepare(settings)
    config = Path('/game/game/csgo/cfg/cs2-local.cfg')
    config.parent.mkdir(parents=True, exist_ok=True)
    lines = {'hostname': settings['server_name'], 'rcon_password': settings['rcon_password'],
             'sv_password': settings['join_password'], 'sv_lan': 0}
    os.umask(0o077)
    config.write_text('\n'.join(f'{key} {quoted(value)}' for key, value in lines.items()) + '\n')
    config.chmod(0o600)
    os.chdir('/game/game')
    os.environ['SteamAppId'] = '730'
    # CS2 can bind RCON to container loopback. A separate internal proxy makes it
    # reachable by the panel without exposing RCON on the host's LAN interface.
    proxy_port = settings['port'] + 1 if settings['port'] < 65535 else 65534
    subprocess.Popen(['socat', f'TCP-LISTEN:{proxy_port},bind=0.0.0.0,reuseaddr,fork',
                      f'TCP:127.0.0.1:{settings["port"]}'])
    game_type, game_mode = (1, 2) if settings['game_mode'] == 'deathmatch' else (0, 1)
    args = ['/bin/bash', '/game/game/cs2.sh', '-dedicated', '-console', '-usercon', '-ip', '0.0.0.0', '-port',
            str(settings['port']), '-maxplayers', str(settings['max_players']),
            '+game_type', str(game_type), '+game_mode', str(game_mode), '+map', settings['map'],
            '+exec', 'mode_' + settings['game_mode'] + '.cfg', '+exec', 'panel_runtime.cfg']
    if settings['gslt']:
        args.extend(['+sv_setsteamaccount', settings['gslt']])
    os.execv(args[0], args)

if __name__ == '__main__':
    main()
