#!/usr/bin/env python3
"""Deploy one declarative CS2 mode into a shared game installation.

The base CS2, Metamod and CounterStrikeSharp installation is never managed by
this module. Only exact targets declared by the selected mode manifest are
copied, inventoried and removed on the next switch.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MODE_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
CFG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.cfg$")
MAP_RE = re.compile(r"^[a-z0-9_]+$")
GAME_ALIASES = {"competitive", "casual", "wingman", "deathmatch"}
RELATIVE_TARGET_PREFIXES = ("addons/", "cfg/")
ABSOLUTE_TARGET_PREFIX = "/addons/"
INVENTORY_VERSION = 1
VERSION_KEYS = ("metamod", "counterstrikesharp")
RESERVED_RELATIVE_TARGETS = {
    "addons",
    "addons/counterstrikesharp",
    "addons/counterstrikesharp/plugins",
    "addons/counterstrikesharp/shared",
    "addons/counterstrikesharp/configs",
    "addons/metamod",
    "cfg",
}
RESERVED_ABSOLUTE_TARGETS = {"/addons"}


class ApplyError(RuntimeError):
    """A mode cannot be validated or safely deployed."""


@dataclass(frozen=True)
class Entry:
    source: Path
    target: Path
    target_key: str
    kind: str
    absolute: bool
    owner: str

    def inventory_row(self) -> dict:
        return {
            "target": self.target_key,
            "kind": self.kind,
            "absolute": self.absolute,
            "owner": self.owner,
        }


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ApplyError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ApplyError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ApplyError(f"Expected a JSON object in {path}")
    return value



def _validate_versions(
    manifest: dict,
    versions_path: Path | None,
    installed_versions_path: Path | None,
) -> None:
    requirements = manifest.get("requires")
    if not isinstance(requirements, dict):
        raise ApplyError("manifest.requires must declare metamod and counterstrikesharp")
    expected_versions: dict[str, str] = {}
    for key in VERSION_KEYS:
        expected = requirements.get(key)
        if not isinstance(expected, str) or not expected.strip():
            raise ApplyError(f"manifest.requires.{key} is missing or invalid")
        expected_versions[key] = expected

    if versions_path is not None:
        versions = _read_json(versions_path)
        for key, expected in expected_versions.items():
            declared = versions.get(key)
            actual = declared.get("version") if isinstance(declared, dict) else None
            if actual != expected:
                raise ApplyError(
                    f"Mode requires {key} {expected}, but manager/versions.json declares {actual!r}"
                )

    if installed_versions_path is not None:
        installed = _read_json(installed_versions_path)
        for key, expected in expected_versions.items():
            actual = installed.get(key)
            if actual != expected:
                raise ApplyError(
                    f"Mode requires installed {key} {expected}, but server marker declares {actual!r}"
                )


def _safe_relative(raw: object, label: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ApplyError(f"{label} must be a non-empty relative path")
    if raw.startswith(("/", "\\")) or "\\" in raw or ":" in raw:
        raise ApplyError(f"{label} must be a relative POSIX path")
    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ApplyError(f"{label} contains an unsafe path segment")
    return raw


def _resolve_source(root: Path, raw: object, label: str) -> Path:
    relative = _safe_relative(raw, label)
    resolved_root = root.resolve()
    resolved = root.joinpath(*relative.split("/")).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ApplyError(f"{label} escapes its source root")
    return resolved


def _target_path(
    raw: object,
    *,
    absolute: bool,
    server_root: Path,
    absolute_root: Path,
    label: str,
) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw:
        raise ApplyError(f"{label} must be a non-empty path")
    if "\\" in raw:
        raise ApplyError(f"{label} contains an unsafe path segment")
    parts = raw.lstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ApplyError(f"{label} contains an unsafe path segment")

    if absolute:
        if not raw.startswith(ABSOLUTE_TARGET_PREFIX):
            raise ApplyError(f"{label} must start with {ABSOLUTE_TARGET_PREFIX}")
        relative = raw.lstrip("/")
        root = absolute_root.resolve()
        target = root.joinpath(*relative.split("/")).resolve()
        key = "/" + relative
        if key.rstrip("/") in RESERVED_ABSOLUTE_TARGETS:
            raise ApplyError(f"{label} is a reserved framework root")
    else:
        if raw.startswith("/") or not raw.startswith(RELATIVE_TARGET_PREFIXES):
            raise ApplyError(
                f"{label} must start with {' or '.join(RELATIVE_TARGET_PREFIXES)}"
            )
        root = (server_root / "game" / "csgo").resolve()
        target = root.joinpath(*raw.split("/")).resolve()
        key = raw.rstrip("/")
        if key in RESERVED_RELATIVE_TARGETS:
            raise ApplyError(f"{label} is a reserved framework root")

    if target != root and root not in target.parents:
        raise ApplyError(f"{label} escapes its target root")
    return target, key


def _mount_entry(
    raw: object,
    *,
    owner: str,
    mode_root: Path,
    shared_root: Path,
    server_root: Path,
    absolute_root: Path,
    label: str,
) -> Entry:
    if not isinstance(raw, dict):
        raise ApplyError(f"{label} must be an object")
    shared = bool(raw.get("shared", False))
    absolute = bool(raw.get("absolute", False))
    kind = raw.get("kind", "dir")
    if kind not in ("file", "dir"):
        raise ApplyError(f"{label}.kind must be file or dir")
    source_root = shared_root if shared else mode_root
    source = _resolve_source(source_root, raw.get("source"), f"{label}.source")
    target, target_key = _target_path(
        raw.get("target"),
        absolute=absolute,
        server_root=server_root,
        absolute_root=absolute_root,
        label=f"{label}.target",
    )
    if kind == "file" and not source.is_file():
        raise ApplyError(f"Missing declared file for {owner}: {source}")
    if kind == "dir" and not source.is_dir():
        raise ApplyError(f"Missing declared directory for {owner}: {source}")
    return Entry(source, target, target_key, kind, absolute, owner)


def _startup_entries(
    manifest: dict,
    *,
    mode_root: Path,
    server_root: Path,
    absolute_root: Path,
) -> list[Entry]:
    startup = manifest.get("startup")
    if not isinstance(startup, dict):
        raise ApplyError("manifest.startup must be an object")
    result: list[Entry] = []
    for field in ("mode_cfg", "runtime_cfg"):
        name = startup.get(field)
        if not isinstance(name, str) or not CFG_RE.fullmatch(name):
            raise ApplyError(f"manifest.startup.{field} is invalid")
        result.append(
            _mount_entry(
                {"source": f"cfg/{name}", "target": f"cfg/{name}", "kind": "file"},
                owner=field,
                mode_root=mode_root,
                shared_root=mode_root,
                server_root=server_root,
                absolute_root=absolute_root,
                label=f"startup.{field}",
            )
        )
    return result


def build_entries(
    manifest: dict,
    *,
    mode_root: Path,
    shared_root: Path,
    server_root: Path,
    absolute_root: Path,
) -> list[Entry]:
    entries = _startup_entries(
        manifest,
        mode_root=mode_root,
        server_root=server_root,
        absolute_root=absolute_root,
    )
    plugins = manifest.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        raise ApplyError("manifest.plugins must be a non-empty list")
    for plugin_index, plugin in enumerate(plugins):
        if not isinstance(plugin, dict):
            raise ApplyError(f"manifest.plugins[{plugin_index}] must be an object")
        owner = plugin.get("name")
        if not isinstance(owner, str) or not owner:
            raise ApplyError(f"manifest.plugins[{plugin_index}].name is invalid")
        mounts = plugin.get("mounts")
        if not isinstance(mounts, list) or not mounts:
            raise ApplyError(f"Plugin {owner} has no mounts")
        for mount_index, mount in enumerate(mounts):
            entries.append(
                _mount_entry(
                    mount,
                    owner=owner,
                    mode_root=mode_root,
                    shared_root=shared_root,
                    server_root=server_root,
                    absolute_root=absolute_root,
                    label=f"plugins[{plugin_index}].mounts[{mount_index}]",
                )
            )

    configs = manifest.get("configs", [])
    if not isinstance(configs, list):
        raise ApplyError("manifest.configs must be a list")
    for config_index, config in enumerate(configs):
        if not isinstance(config, dict):
            raise ApplyError(f"manifest.configs[{config_index}] must be an object")
        name = config.get("name")
        if not isinstance(name, str) or not name:
            raise ApplyError(f"manifest.configs[{config_index}].name is invalid")
        entries.append(
            _mount_entry(
                config,
                owner=name,
                mode_root=mode_root,
                shared_root=shared_root,
                server_root=server_root,
                absolute_root=absolute_root,
                label=f"configs[{config_index}]",
            )
        )

    return _deduplicate_entries(entries)


def _contains(parent: Entry, child: Entry) -> bool:
    if parent.kind != "dir" or parent.absolute != child.absolute:
        return False
    try:
        child.target.relative_to(parent.target)
        child.source.relative_to(parent.source)
    except ValueError:
        return False
    return True


def _deduplicate_entries(entries: list[Entry]) -> list[Entry]:
    """Remove exact duplicates and files already carried by a directory copy."""
    unique: list[Entry] = []
    by_target: dict[Path, Entry] = {}
    for entry in entries:
        existing = by_target.get(entry.target)
        if existing:
            if existing.source != entry.source or existing.kind != entry.kind:
                raise ApplyError(f"Conflicting declarations for target {entry.target_key}")
            continue
        by_target[entry.target] = entry
        unique.append(entry)

    result: list[Entry] = []
    for entry in unique:
        if any(other is not entry and _contains(other, entry) for other in unique):
            continue
        result.append(entry)
    return sorted(result, key=lambda item: (len(item.target.parts), item.target_key))


def _load_inventory(path: Path) -> dict:
    if not path.exists():
        return {"version": INVENTORY_VERSION, "mode": None, "entries": []}
    data = _read_json(path)
    if data.get("version") != INVENTORY_VERSION or not isinstance(data.get("entries"), list):
        raise ApplyError(f"Unsupported or invalid inventory: {path}")
    return data


def _inventory_target(
    row: dict, *, server_root: Path, absolute_root: Path
) -> Path:
    if not isinstance(row, dict):
        raise ApplyError("Invalid inventory row")
    target, _ = _target_path(
        row.get("target"),
        absolute=bool(row.get("absolute", False)),
        server_root=server_root,
        absolute_root=absolute_root,
        label="inventory.target",
    )
    return target


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_symlink():
        destination.symlink_to(
            os.readlink(source),
            target_is_directory=source.is_dir(),
        )
    elif source.is_file():
        shutil.copy2(source, destination)
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        raise ApplyError(f"Cannot move unsupported path: {source}")


def _move_path(source: Path, destination: Path) -> None:
    """Move a path atomically at the destination, including across filesystems."""
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() or destination.is_symlink():
        raise ApplyError(f"Move destination already exists: {destination}")

    try:
        source.rename(destination)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise

    if source.is_dir() and not source.is_symlink():
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.move-",
                dir=destination.parent,
            )
        )
        shutil.rmtree(temporary)
    else:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.move-",
            dir=destination.parent,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        temporary.unlink()

    try:
        _copy_path(source, temporary)
        temporary.rename(destination)

        try:
            _remove(source)
        except Exception:
            _remove(destination)
            raise
    except Exception:
        _remove(temporary)
        raise


def _validate_source_tree(entry: Entry) -> None:
    if entry.source.is_symlink():
        raise ApplyError(f"Symlink sources are not allowed for {entry.owner}: {entry.source}")
    if entry.kind == "dir":
        for child in entry.source.rglob("*"):
            if child.is_symlink():
                raise ApplyError(
                    f"Symlink inside source tree is not allowed for {entry.owner}: {child}"
                )


def _copy_to_staging(entry: Entry, transaction_root: Path, index: int) -> Path:
    _validate_source_tree(entry)
    staging = transaction_root / "staging" / str(index)
    staging.parent.mkdir(parents=True, exist_ok=True)
    if entry.kind == "file":
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.source, staging)
    else:
        shutil.copytree(entry.source, staging, symlinks=False)
    return staging


def _backup_previous(
    inventory: dict,
    *,
    transaction_root: Path,
    server_root: Path,
    absolute_root: Path,
) -> list[tuple[dict, Path, Path]]:
    backups: list[tuple[dict, Path, Path]] = []
    rows = sorted(
        inventory.get("entries", []),
        key=lambda row: len(str(row.get("target", "")).split("/")),
        reverse=True,
    )
    for index, row in enumerate(rows):
        target = _inventory_target(row, server_root=server_root, absolute_root=absolute_root)
        if not target.exists() and not target.is_symlink():
            continue
        backup = transaction_root / "previous" / str(index)
        backup.parent.mkdir(parents=True, exist_ok=True)
        _move_path(target, backup)
        backups.append((row, target, backup))
    return backups


def _backup_new_conflicts(
    entries: list[Entry],
    previous: dict,
    *,
    transaction_root: Path,
    server_root: Path,
    absolute_root: Path,
) -> list[tuple[dict, Path, Path]]:
    """Back up exact pre-existing targets not owned by the previous inventory.

    This supports safe adoption on the first deployment and guarantees rollback
    never destroys a legacy file that happened to occupy a declared target.
    """
    previous_targets = {
        _inventory_target(row, server_root=server_root, absolute_root=absolute_root)
        for row in previous.get("entries", [])
    }
    backups: list[tuple[dict, Path, Path]] = []
    for index, entry in enumerate(entries):
        if entry.target in previous_targets:
            continue
        if not entry.target.exists() and not entry.target.is_symlink():
            continue
        backup = transaction_root / "adopted" / str(index)
        backup.parent.mkdir(parents=True, exist_ok=True)
        _move_path(entry.target, backup)
        backups.append((entry.inventory_row(), entry.target, backup))
    return backups


def _install_staging(entries: list[Entry], staged: list[Path]) -> list[Path]:
    if len(entries) != len(staged):
        raise ApplyError(
            f"Internal staging count mismatch: {len(entries)} entries, "
            f"{len(staged)} staged paths"
        )
    installed: list[Path] = []
    for entry, staging in zip(entries, staged):
        entry.target.parent.mkdir(parents=True, exist_ok=True)
        _remove(entry.target)
        _move_path(staging, entry.target)
        installed.append(entry.target)
    return installed


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _write_env(path: Path, *, mode: str, manifest: dict, settings: dict) -> None:
    startup = manifest["startup"]
    alias = startup.get("game_alias")
    mode_cfg = startup.get("mode_cfg")
    runtime_cfg = startup.get("runtime_cfg")
    map_name = settings.get("map")
    capacity = settings.get("capacity")
    if alias not in GAME_ALIASES:
        raise ApplyError("Unsupported game alias")
    if not isinstance(mode_cfg, str) or not CFG_RE.fullmatch(mode_cfg):
        raise ApplyError("Invalid mode cfg")
    if not isinstance(runtime_cfg, str) or not CFG_RE.fullmatch(runtime_cfg):
        raise ApplyError("Invalid runtime cfg")
    if not isinstance(map_name, str) or not MAP_RE.fullmatch(map_name):
        raise ApplyError("Invalid start map")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 64:
        raise ApplyError("Invalid capacity")
    values = {
        "CS2_ACTIVE_MODE": mode,
        "CS2_GAMEALIAS": alias,
        "CS2_MAXPLAYERS": str(capacity),
        "CS2_STARTMAP": map_name,
        "CS2_MODE_CFG": mode_cfg,
        "CS2_RUNTIME_CFG": runtime_cfg,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{key}={value}\n" for key, value in values.items())
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, path)


def apply_mode(
    *,
    state_path: Path,
    modes_root: Path,
    shared_root: Path,
    server_root: Path,
    inventory_path: Path,
    env_path: Path,
    absolute_root: Path = Path("/"),
    versions_path: Path | None = None,
    installed_versions_path: Path | None = None,
) -> dict:
    state = _read_json(state_path)
    mode = state.get("mode")
    settings = state.get("settings")
    if not isinstance(mode, str) or not MODE_RE.fullmatch(mode):
        raise ApplyError("active mode is missing or invalid")
    if not isinstance(settings, dict):
        raise ApplyError("active mode settings are missing or invalid")
    mode_root = modes_root / mode
    manifest = _read_json(mode_root / "mode.json")
    if manifest.get("id") != mode:
        raise ApplyError("mode manifest id does not match the selected mode")
    _validate_versions(manifest, versions_path, installed_versions_path)

    entries = build_entries(
        manifest,
        mode_root=mode_root,
        shared_root=shared_root,
        server_root=server_root,
        absolute_root=absolute_root,
    )
    previous = _load_inventory(inventory_path)
    transaction_parent = inventory_path.parent / ".transactions"
    transaction_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"{mode}-", dir=transaction_parent) as temp_dir:
        transaction_root = Path(temp_dir)
        staged = [_copy_to_staging(entry, transaction_root, i) for i, entry in enumerate(entries)]
        backups: list[tuple[dict, Path, Path]] = []
        adopted: list[tuple[dict, Path, Path]] = []
        installed: list[Path] = []
        try:
            backups = _backup_previous(
                previous,
                transaction_root=transaction_root,
                server_root=server_root,
                absolute_root=absolute_root,
            )
            adopted = _backup_new_conflicts(
                entries,
                previous,
                transaction_root=transaction_root,
                server_root=server_root,
                absolute_root=absolute_root,
            )
            installed = _install_staging(entries, staged)
            next_inventory = {
                "version": INVENTORY_VERSION,
                "mode": mode,
                "entries": [entry.inventory_row() for entry in entries],
            }
            _atomic_json(inventory_path, next_inventory)
            _write_env(env_path, mode=mode, manifest=manifest, settings=settings)
        except Exception as exc:
            for target in reversed(installed):
                _remove(target)
            for _row, target, backup in reversed(adopted):
                target.parent.mkdir(parents=True, exist_ok=True)
                _remove(target)
                _move_path(backup, target)
            for _row, target, backup in reversed(backups):
                target.parent.mkdir(parents=True, exist_ok=True)
                _remove(target)
                _move_path(backup, target)
            _atomic_json(inventory_path, previous)
            if isinstance(exc, ApplyError):
                raise
            raise ApplyError(f"Mode deployment failed and was rolled back: {exc}") from exc

    return {
        "mode": mode,
        "entries": len(entries),
        "previous_mode": previous.get("mode"),
        "env": str(env_path),
    }



def cleanup_managed(
    *,
    inventory_path: Path,
    server_root: Path,
    absolute_root: Path = Path("/"),
) -> dict:
    """Remove only the currently inventoried mode layer, transactionally."""
    previous = _load_inventory(inventory_path)
    transaction_parent = inventory_path.parent / ".transactions"
    transaction_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cleanup-", dir=transaction_parent) as temp_dir:
        transaction_root = Path(temp_dir)
        backups: list[tuple[dict, Path, Path]] = []
        try:
            backups = _backup_previous(
                previous,
                transaction_root=transaction_root,
                server_root=server_root,
                absolute_root=absolute_root,
            )
            _atomic_json(
                inventory_path,
                {"version": INVENTORY_VERSION, "mode": None, "entries": []},
            )
        except Exception as exc:
            for _row, target, backup in reversed(backups):
                target.parent.mkdir(parents=True, exist_ok=True)
                _remove(target)
                _move_path(backup, target)
            _atomic_json(inventory_path, previous)
            if isinstance(exc, ApplyError):
                raise
            raise ApplyError(f"Managed cleanup failed and was rolled back: {exc}") from exc
    return {
        "previous_mode": previous.get("mode"),
        "removed_entries": len(backups),
    }

def sync_config(
    *,
    mode: str,
    name: str,
    modes_root: Path,
    shared_root: Path,
    server_root: Path,
    inventory_path: Path,
    absolute_root: Path = Path("/"),
    versions_path: Path | None = None,
    installed_versions_path: Path | None = None,
) -> dict:
    if not MODE_RE.fullmatch(mode):
        raise ApplyError("Invalid mode")
    inventory = _load_inventory(inventory_path)
    if inventory.get("mode") != mode:
        raise ApplyError(f"Mode {mode} is not deployed")
    mode_root = modes_root / mode
    manifest = _read_json(mode_root / "mode.json")
    _validate_versions(manifest, versions_path, installed_versions_path)
    configs = manifest.get("configs", [])
    selected = next(
        (config for config in configs if isinstance(config, dict) and config.get("name") == name),
        None,
    )
    if selected is None:
        raise ApplyError(f"Mode {mode} does not declare config {name!r}")
    entry = _mount_entry(
        selected,
        owner=name,
        mode_root=mode_root,
        shared_root=shared_root,
        server_root=server_root,
        absolute_root=absolute_root,
        label="config",
    )
    inventory_targets = [
        _inventory_target(row, server_root=server_root, absolute_root=absolute_root)
        for row in inventory.get("entries", [])
    ]
    if not any(entry.target == target or target in entry.target.parents for target in inventory_targets):
        raise ApplyError(f"Config target {entry.target_key} is not owned by the active inventory")
    _validate_source_tree(entry)
    entry.target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="config-", dir=entry.target.parent) as temp_dir:
        transaction_root = Path(temp_dir)
        staged = transaction_root / "staged"
        backup = transaction_root / "previous"
        if entry.kind == "file":
            shutil.copy2(entry.source, staged)
        else:
            shutil.copytree(entry.source, staged, symlinks=False)
        had_previous = entry.target.exists() or entry.target.is_symlink()
        try:
            if had_previous:
                _move_path(entry.target, backup)
            _move_path(staged, entry.target)
        except Exception as exc:
            _remove(entry.target)
            if had_previous and backup.exists():
                _move_path(backup, entry.target)
            raise ApplyError(f"Config sync failed and was rolled back: {exc}") from exc
    return {"mode": mode, "config": name, "target": entry.target_key}


def verify_mode(
    *,
    mode: str,
    modes_root: Path,
    shared_root: Path,
    server_root: Path,
    absolute_root: Path = Path("/"),
    versions_path: Path | None = None,
    installed_versions_path: Path | None = None,
) -> dict:
    if not MODE_RE.fullmatch(mode):
        raise ApplyError("Invalid mode")
    mode_root = modes_root / mode
    manifest = _read_json(mode_root / "mode.json")
    _validate_versions(manifest, versions_path, installed_versions_path)
    entries = build_entries(
        manifest,
        mode_root=mode_root,
        shared_root=shared_root,
        server_root=server_root,
        absolute_root=absolute_root,
    )
    return {"mode": mode, "entries": [entry.inventory_row() for entry in entries]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes-root", type=Path, default=Path("/manager/modes"))
    parser.add_argument("--shared-root", type=Path, default=Path("/manager/shared"))
    parser.add_argument("--server-root", type=Path, default=Path("/home/steam/cs2-dedicated"))
    parser.add_argument("--inventory", type=Path, default=Path("/home/steam/cs2-dedicated/.cs2-manager/managed-files.json"))
    parser.add_argument("--absolute-root", type=Path, default=Path("/"), help=argparse.SUPPRESS)
    parser.add_argument("--versions", type=Path, default=Path("/manager/versions.json"))
    parser.add_argument(
        "--installed-versions",
        type=Path,
        default=Path("/home/steam/cs2-dedicated/game/csgo/addons/.cs2-manager-versions.json"),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--state", type=Path, default=Path("/manager/data/runtime/active-mode.json"))
    apply_parser.add_argument("--env", type=Path, default=Path("/tmp/cs2-mode.env"))

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("mode")

    sub.add_parser("cleanup")

    sync_parser = sub.add_parser("sync-config")
    sync_parser.add_argument("mode")
    sync_parser.add_argument("name")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "apply":
            result = apply_mode(
                state_path=args.state,
                modes_root=args.modes_root,
                shared_root=args.shared_root,
                server_root=args.server_root,
                inventory_path=args.inventory,
                env_path=args.env,
                absolute_root=args.absolute_root,
                versions_path=args.versions,
                installed_versions_path=args.installed_versions,
            )
        elif args.command == "verify":
            result = verify_mode(
                mode=args.mode,
                modes_root=args.modes_root,
                shared_root=args.shared_root,
                server_root=args.server_root,
                absolute_root=args.absolute_root,
                versions_path=args.versions,
                installed_versions_path=args.installed_versions,
            )
        elif args.command == "cleanup":
            result = cleanup_managed(
                inventory_path=args.inventory,
                server_root=args.server_root,
                absolute_root=args.absolute_root,
            )
        else:
            result = sync_config(
                mode=args.mode,
                name=args.name,
                modes_root=args.modes_root,
                shared_root=args.shared_root,
                server_root=args.server_root,
                inventory_path=args.inventory,
                absolute_root=args.absolute_root,
                versions_path=args.versions,
                installed_versions_path=args.installed_versions,
            )
    except ApplyError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
