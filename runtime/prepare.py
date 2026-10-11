"""Install the permanent framework and transactionally deploy exactly one mode."""
import json
import os
import re
import shutil
from pathlib import Path

from mode_manager import apply_mode


def repair_metamod(path):
    path = Path(path)
    original = path.read_text()
    match = re.search(r'\bSearchPaths\s*\{', original)
    if not match:
        raise ValueError('gameinfo.gi has no SearchPaths block')
    end = original.find('}', match.end())
    active = re.sub(r'//[^\n]*', '', original[match.end():end])
    if re.search(r'^\s*Game\s+csgo/addons/metamod\s*$', active, re.M):
        return
    backup = path.with_suffix('.gi.cs2-local-backup')
    shutil.copy2(path, backup)
    temporary = path.with_suffix('.gi.tmp')
    temporary.write_text(original[:match.end()] + '\n\t\t\tGame\tcsgo/addons/metamod' + original[match.end():])
    os.replace(temporary, path)


def prepare(settings, game='/game', assets='/opt/cs2', force_frameworks=False):
    game, assets = Path(game), Path(assets)
    csgo = game / 'game/csgo'
    state = game / '.cs2-local'
    state.mkdir(parents=True, exist_ok=True)
    version_file = assets / 'frameworks/versions.json'
    versions = json.loads(version_file.read_text())
    marker = csgo / 'addons/.cs2-local-versions.json'
    required = ['addons/metamod', 'addons/counterstrikesharp/bin/linuxsteamrt64/counterstrikesharp.so',
                'addons/counterstrikesharp/plugins/LocalManager/LocalManager.dll']
    needs_copy = force_frameworks or not marker.exists() or json.loads(marker.read_text()) != versions or any(not (csgo / p).exists() for p in required)
    if needs_copy:
        shutil.copytree(assets / 'frameworks/addons', csgo / 'addons', dirs_exist_ok=True)
        marker.write_text(json.dumps(versions))
    repair_metamod(csgo / 'gameinfo.gi')
    admins = csgo / 'addons/counterstrikesharp/configs/admins.json'
    admins.parent.mkdir(parents=True, exist_ok=True)
    if not admins.is_symlink() or str(admins.readlink()) != '/control/admins.json':
        admins.unlink(missing_ok=True)
        admins.symlink_to('/control/admins.json')
    mode = settings['game_mode']
    runtime = state / 'runtime' / mode / 'panel_runtime.cfg'
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text('exec cs2-local.cfg\n')
    base = state / 'server.cfg'
    base.write_text('exec cs2-local.cfg\n')
    active = state / 'active-mode.json'
    active.write_text(json.dumps({'mode': mode, 'settings': {'capacity': settings['max_players'], 'map': settings['map']}}))
    if mode == 'retakes':
        relative = Path('addons/counterstrikesharp/configs/plugins/RetakesPlugin/RetakesPlugin.json')
        config = json.loads((assets / 'modes/retakes' / relative).read_text())
        # Slots are configurable; Retakes supports at most 10 active players.
        config['GameSettings']['MaxPlayers'] = min(settings['max_players'], 10)
        override = state / 'configs/retakes' / relative
        override.parent.mkdir(parents=True, exist_ok=True)
        override.write_text(json.dumps(config, indent=2))
    return apply_mode(modes_root=assets / 'modes', server_root=game, state_root=state,
                      server_config=base, versions_path=assets / 'components.json',
                      installed_versions_path=marker, state_path=active)


if __name__ == '__main__':
    print(json.dumps(prepare(json.loads(Path('/config/server.json').read_text()), force_frameworks=True)))
