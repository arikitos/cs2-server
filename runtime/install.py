"""Stream SteamCMD output and require explicit download success, not just exit 0."""
import subprocess
import sys

arguments = ['/opt/steamcmd/steamcmd.sh', '+force_install_dir', '/game', '+login',
             'anonymous', '+app_update', '730']
if len(sys.argv) > 1 and sys.argv[1] == 'validate':
    arguments.append('validate')
process = subprocess.Popen(arguments + ['+quit'], cwd='/opt/steamcmd',
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
success = False
for line in process.stdout:
    print(line, end='', flush=True)
    if "Success! App '730'" in line and ('fully installed' in line or 'already up to date' in line):
        success = True
code = process.wait()
if code or not success:
    raise SystemExit(code or 1)
