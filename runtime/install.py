"""Stream SteamCMD output and require explicit download success, not just exit 0."""
import subprocess
import sys
from pathlib import Path


def steamcmd_arguments(operation, game='/game'):
    if operation not in {'install', 'update', 'validate'}:
        raise ValueError('Unknown Steam installation operation')
    arguments = ['/opt/steamcmd/steamcmd.sh', '+force_install_dir', str(game), '+login',
                 'anonymous', '+app_update', '730']
    if operation in {'install', 'validate'}:
        arguments.append('validate')
    return arguments + ['+quit']


def run(operation='install', game='/game'):
    arguments = steamcmd_arguments(operation, game)
    Path(game).mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(arguments, cwd='/opt/steamcmd',
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    success = False
    for line in process.stdout:
        print(line, end='', flush=True)
        if "Success! App '730'" in line and ('fully installed' in line or 'already up to date' in line):
            success = True
    code = process.wait()
    return code or (0 if success else 1)


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else 'install'))
