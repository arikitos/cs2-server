"""Prepare pinned upstream assets at image build time, never at game startup."""
import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def safe_path(root, name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        raise ValueError('Unsafe archive member: ' + name)
    target = Path(root).joinpath(*path.parts)
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Archive member escapes destination')
    return target


def extract(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                target = safe_path(destination, member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError('Symbolic links are not accepted in plugin archives')
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as incoming, target.open('wb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                    target.chmod(0o755 if mode & 0o111 or target.suffix == '.so' else 0o644)
    else:
        with tarfile.open(archive) as source:
            for member in source:
                target = safe_path(destination, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as incoming, target.open('wb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                    target.chmod(member.mode & 0o777)
                else:
                    raise ValueError('Unsupported archive member: ' + member.name)


def download(component, destination):
    request = urllib.request.Request(component['url'], headers={'User-Agent': 'CS2-Local/2'})
    with urllib.request.urlopen(request, timeout=120) as response, Path(destination).open('wb') as output:
        shutil.copyfileobj(response, output)
    digest = hashlib.sha256(Path(destination).read_bytes()).hexdigest()
    if component.get('sha256') and digest != component['sha256']:
        raise ValueError('Release checksum did not match: ' + component['url'])
    return digest


def copy_payload(source, destination):
    """Handle CSSharp-relative plugin releases and csgo-relative MatchZy releases."""
    source, destination = Path(source), Path(destination)
    if (source / 'addons').is_dir():
        payload = source
    elif (source / 'plugins').is_dir():
        payload = source
        destination = destination / 'addons/counterstrikesharp'
    else:
        raise ValueError('Release does not contain the expected addons/plugins tree')
    shutil.copytree(payload, destination, dirs_exist_ok=True)


def main():
    root = Path(__file__).parent
    components = json.loads((root / 'components.json').read_text())
    frameworks = root / 'frameworks'
    modes = root / 'modes'
    hashes = {}
    with tempfile.TemporaryDirectory() as directory:
        for name, component in components.items():
            print('Preparing ' + name + ' ' + component['version'], flush=True)
            archive = Path(directory) / (name + '.archive')
            hashes[name] = download(component, archive)
            unpacked = Path(directory) / name
            extract(archive, unpacked)
            if name in {'metamod', 'counterstrikesharp'}:
                copy_payload(unpacked, frameworks)
            else:
                mode = 'matchzy' if name == 'matchzy' else 'retakes'
                # Upstream releases must not overwrite the owner's legacy configuration.
                with tempfile.TemporaryDirectory() as config_backup:
                    previous = Path(config_backup) / 'previous'
                    shutil.copytree(modes / mode, previous)
                    copy_payload(unpacked, modes / mode)
                    shutil.copytree(previous, modes / mode, dirs_exist_ok=True)
    # The source-built bridge is global and must never be removed by a mode switch.
    shutil.copytree('/built/LocalManager', frameworks / 'addons/counterstrikesharp/plugins/LocalManager', dirs_exist_ok=True)
    shutil.copytree('/built/RetakesAllocator', modes / 'retakes/addons/counterstrikesharp/plugins/RetakesAllocator', dirs_exist_ok=True)
    gamedata = modes / 'retakes/addons/counterstrikesharp/plugins/RetakesAllocator/gamedata'
    gamedata.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / 'plugins/retakes-allocator/Resources/RetakesAllocator_gamedata.json', gamedata / 'RetakesAllocator_gamedata.json')
    (frameworks / 'addons/counterstrikesharp/configs/admins.json').unlink(missing_ok=True)
    versions = {name: row['version'] for name, row in components.items()}
    versions['asset_hashes'] = hashes
    (frameworks / 'versions.json').write_text(json.dumps(versions, indent=2))
    for path in [frameworks, modes]:
        for member in path.rglob('*'):
            if member.is_dir():
                member.chmod(0o755)
            elif member.is_file():
                member.chmod(0o755 if member.suffix == '.so' or member.stat().st_mode & 0o111 else 0o644)


if __name__ == '__main__':
    main()
