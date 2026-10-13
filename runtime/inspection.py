"""Probe the persistent install; SteamCMD validates all official file contents."""
import json
import os
import shutil
from pathlib import Path

REQUIRED_FILES = (
    'steamapps/appmanifest_730.acf',
    'game/cs2.sh',
    'game/bin/linuxsteamrt64/cs2',
    'game/csgo/gameinfo.gi',
)
EXECUTABLE_FILES = {'game/cs2.sh', 'game/bin/linuxsteamrt64/cs2'}


def inspect_installation(root='/game'):
    root = Path(root)
    manifest = root / REQUIRED_FILES[0]
    missing = []
    for relative in REQUIRED_FILES:
        path = root / relative
        if (not path.is_file() or path.stat().st_size == 0
                or relative in EXECUTABLE_FILES and not os.access(path, os.X_OK)):
            missing.append(relative)
    return {'path': str(root),
            'exists': (root / 'game').exists() or (root / 'steamapps').exists(),
            'manifest': manifest.read_text(errors='replace') if manifest.is_file() else '',
            'missing_files': missing,
            'free_bytes': shutil.disk_usage(root).free}


if __name__ == '__main__':
    print(json.dumps(inspect_installation()))
