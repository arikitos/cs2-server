#!/usr/bin/env python3
"""Deploy one self-contained CS2 mode into a shared server installation.

Every file below ``modes/<mode>/addons`` and ``modes/<mode>/cfg`` is copied to
``game/csgo``.  The inventory records individual files, so switching modes does
not remove Steam files, framework files, or runtime-generated plugin data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


MODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PAYLOAD_ROOTS = ("addons", "cfg")
# The shared server.cfg is always manager-owned and never part of a mode.
SERVER_CONFIG_REL = "cfg/server.cfg"


class ModeError(RuntimeError):
    """An invalid or unsafe mode operation."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModeError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ModeError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ModeError(f"expected a JSON object in {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(value: str, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ModeError(f"unsafe {label}: {value!r}")
    if "\\" in value or "//" in value:
        raise ModeError(f"invalid {label}: {value!r}")
    return path


def _inside(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    resolved_parent = candidate.parent.resolve(strict=False)
    if resolved_parent != resolved_root and resolved_root not in resolved_parent.parents:
        raise ModeError(f"path escapes managed root: {relative}")
    return candidate


def load_manifest(modes_root: Path, mode: str) -> tuple[Path, dict[str, Any]]:
    if not MODE_RE.fullmatch(mode):
        raise ModeError(f"invalid mode id: {mode!r}")
    root = modes_root / mode
    manifest = _read_json(root / "mode.json")
    if manifest.get("id") != mode:
        raise ModeError(f"mode id in {root / 'mode.json'} must be {mode!r}")
    startup = manifest.get("startup")
    if not isinstance(startup, dict):
        raise ModeError(f"mode {mode} has no startup object")
    for key in ("game_alias", "mode_cfg", "runtime_cfg"):
        value = startup.get(key)
        if not isinstance(value, str) or not TOKEN_RE.fullmatch(value):
            raise ModeError(f"mode {mode} has invalid startup.{key}")
    return root, manifest


def _check_requirements(
    manifest: dict[str, Any], versions_path: Path, installed_versions_path: Path
) -> None:
    required = manifest.get("requires", {})
    if not isinstance(required, dict):
        raise ModeError("requires must be an object")
    catalog = _read_json(versions_path)
    installed = _read_json(installed_versions_path)
    for name, wanted in required.items():
        if not isinstance(name, str) or not isinstance(wanted, str):
            raise ModeError("framework requirements must be string pairs")
        catalog_entry = catalog.get(name)
        available = (
            catalog_entry.get("version") if isinstance(catalog_entry, dict) else catalog_entry
        )
        active = installed.get(name)
        if available != wanted:
            raise ModeError(
                f"mode requires {name}={wanted}, repository provides {available!r}"
            )
        if active != wanted:
            raise ModeError(
                f"mode requires {name}={wanted}, server has {active!r}; run setup-on-windows.ps1"
            )


def _payload(mode_root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for root_name in PAYLOAD_ROOTS:
        root = mode_root / root_name
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise ModeError(f"payload root must be a real directory: {root}")
        for source in sorted(root.rglob("*")):
            if source.is_symlink():
                raise ModeError(f"symbolic links are not allowed in modes: {source}")
            if not source.is_file():
                continue
            relative = source.relative_to(mode_root).as_posix()
            _relative(relative, "payload path")
            files[relative] = source
    if not files:
        raise ModeError(f"mode payload is empty: {mode_root}")
    return files


def build_plan(
    modes_root: Path,
    mode: str,
    state_root: Path,
    server_config: Path,
    versions_path: Path,
    installed_versions_path: Path,
) -> tuple[dict[str, Path], dict[str, Any]]:
    mode_root, manifest = load_manifest(modes_root, mode)
    _check_requirements(manifest, versions_path, installed_versions_path)
    plan = _payload(mode_root)

    if not server_config.is_file() or server_config.is_symlink():
        raise ModeError(f"server config missing or unsafe: {server_config}")
    if SERVER_CONFIG_REL in plan:
        raise ModeError(f"{SERVER_CONFIG_REL} is global and must not exist inside a mode")
    plan[SERVER_CONFIG_REL] = server_config

    startup = manifest["startup"]
    mode_cfg = f"cfg/{startup['mode_cfg']}"
    if mode_cfg not in plan:
        raise ModeError(f"mode startup config is missing: {mode_cfg}")
    runtime_cfg = state_root / "runtime" / mode / startup["runtime_cfg"]
    if not runtime_cfg.is_file() or runtime_cfg.is_symlink():
        raise ModeError(f"runtime config is missing: {runtime_cfg}")
    plan[f"cfg/{startup['runtime_cfg']}"] = runtime_cfg

    configs = manifest.get("configs", [])
    if not isinstance(configs, list):
        raise ModeError("configs must be an array")
    for config in configs:
        if not isinstance(config, dict):
            raise ModeError("config declarations must be objects")
        target = config.get("target")
        if not isinstance(target, str):
            raise ModeError("config target must be a string")
        target_rel = _relative(target, "config target").as_posix()
        if target_rel not in plan:
            raise ModeError(f"declared config is not in the mode payload: {target_rel}")
        if config.get("editable", True) is False:
            continue
        override = state_root / "configs" / mode / Path(*PurePosixPath(target_rel).parts)
        if override.exists():
            if override.is_symlink() or not override.is_file():
                raise ModeError(f"config override must be a real file: {override}")
            plan[target_rel] = override

    plugins = manifest.get("plugins", [])
    if not isinstance(plugins, list):
        raise ModeError("plugins must be an array")
    for plugin in plugins:
        if not isinstance(plugin, dict) or not isinstance(plugin.get("path"), str):
            raise ModeError("each plugin must declare a payload path")
        plugin_path = _relative(plugin["path"], "plugin path").as_posix()
        if not any(path == plugin_path or path.startswith(plugin_path + "/") for path in plan):
            raise ModeError(f"plugin payload is missing: {plugin_path}")

    return plan, manifest


def _inventory_files(inventory_path: Path, csgo_root: Path) -> tuple[set[str], bool]:
    if not inventory_path.exists():
        return set(), False
    inventory = _read_json(inventory_path)
    if inventory.get("version") == 2:
        rows = inventory.get("files", [])
        if not isinstance(rows, list):
            raise ModeError("managed inventory files must be an array")
        result = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise ModeError("invalid managed inventory row")
            result.add(_relative(row["path"], "inventory path").as_posix())
        return result, False

    # Version 1 recorded directory roots.  Expand only paths below game/csgo.
    # A permanent backup is retained after the first successful migration.
    result: set[str] = set()
    for row in inventory.get("entries", []):
        if not isinstance(row, dict) or row.get("absolute"):
            continue
        target = row.get("target")
        if not isinstance(target, str):
            continue
        relative = _relative(target, "legacy inventory path")
        existing = _inside(csgo_root, relative)
        if row.get("kind") == "file":
            if existing.is_file():
                result.add(relative.as_posix())
        elif existing.is_dir():
            for path in existing.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    result.add(path.relative_to(csgo_root).as_posix())
    return result, True


def _remove_empty_parents(path: Path, stop: Path) -> None:
    parent = path.parent
    while parent != stop and stop in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def deploy(
    *,
    mode: str,
    plan: dict[str, Path],
    csgo_root: Path,
    state_root: Path,
    inventory_path: Path,
) -> dict[str, Any]:
    csgo_root.mkdir(parents=True, exist_ok=True)
    previous, legacy = _inventory_files(inventory_path, csgo_root)
    wanted = set(plan)

    for relative, source in plan.items():
        # A fresh Steam depot always ships its own cfg/server.cfg, and an updater
        # validation restores it.  That file is manager-owned by contract, so the
        # base-game copy is adopted through the transaction backup below instead
        # of deadlocking every first activation.
        if relative == SERVER_CONFIG_REL:
            continue
        destination = _inside(csgo_root, _relative(relative, "deployment path"))
        if destination.exists() and relative not in previous:
            if not destination.is_file() or _sha256(destination) != _sha256(source):
                raise ModeError(
                    f"unmanaged file blocks deployment: {destination}; move it or make it identical"
                )

    # os.replace cannot cross filesystems.  The state directory and the CS2
    # installation are separate bind mounts under Docker Desktop, so the staging
    # and backup trees have to live on the installation filesystem for the switch
    # to stay atomic.
    transactions = csgo_root / ".cs2-manager-transactions"
    transactions.mkdir(parents=True, exist_ok=True)
    transaction_root = Path(tempfile.mkdtemp(prefix="mode-", dir=transactions))
    staged_root = transaction_root / "staged"
    backup_root = transaction_root / "backup"
    installed: list[Path] = []
    backed_up: list[tuple[Path, Path]] = []
    try:
        for relative, source in plan.items():
            staged = staged_root / Path(*PurePosixPath(relative).parts)
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staged)

        affected = sorted(previous | wanted)
        for relative in affected:
            destination = _inside(csgo_root, _relative(relative, "deployment path"))
            if destination.exists():
                backup = backup_root / Path(*PurePosixPath(relative).parts)
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
                backed_up.append((destination, backup))

        for relative in sorted(wanted):
            destination = _inside(csgo_root, _relative(relative, "deployment path"))
            staged = staged_root / Path(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, destination)
            installed.append(destination)

        inventory = {
            "version": 2,
            "mode": mode,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "files": [
                {
                    "path": relative,
                    "sha256": _sha256(_inside(csgo_root, _relative(relative, "inventory path"))),
                    "source": str(plan[relative]),
                }
                for relative in sorted(wanted)
            ],
        }
        if legacy and backup_root.exists():
            keep = state_root / "backups" / (
                "legacy-mode-layout-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            )
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(backup_root, keep)
        for relative in previous - wanted:
            _remove_empty_parents(
                _inside(csgo_root, _relative(relative, "deployment path")), csgo_root
            )
        _write_json(inventory_path, inventory)
        return inventory
    except Exception:
        for destination in reversed(installed):
            destination.unlink(missing_ok=True)
        for destination, backup in reversed(backed_up):
            destination.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                os.replace(backup, destination)
        raise
    finally:
        shutil.rmtree(transaction_root, ignore_errors=True)


def apply_mode(
    *,
    modes_root: Path,
    server_root: Path,
    state_root: Path,
    server_config: Path,
    versions_path: Path,
    installed_versions_path: Path,
    state_path: Path,
    env_path: Path | None = None,
) -> dict[str, Any]:
    state = _read_json(state_path)
    mode = state.get("mode")
    settings = state.get("settings", {})
    if not isinstance(mode, str) or not isinstance(settings, dict):
        raise ModeError("active mode state must contain mode and settings")
    startup_preview = load_manifest(modes_root, mode)[1]["startup"]
    capacity = settings.get("capacity", 10)
    if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 64:
        raise ModeError("active mode capacity must be an integer between 1 and 64")
    env_values = {
        "CS2_ACTIVE_MODE": mode,
        "CS2_GAMEALIAS": str(settings.get("game_alias", startup_preview["game_alias"])),
        "CS2_MAXPLAYERS": str(capacity),
        "CS2_STARTMAP": str(settings.get("map", "de_dust2")),
        "CS2_MODE_CFG": startup_preview["mode_cfg"],
        "CS2_RUNTIME_CFG": startup_preview["runtime_cfg"],
    }
    for key, value in env_values.items():
        if not TOKEN_RE.fullmatch(value):
            raise ModeError(f"unsafe runtime value for {key}: {value!r}")
    plan, manifest = build_plan(
        modes_root, mode, state_root, server_config, versions_path, installed_versions_path
    )
    csgo_root = server_root / "game" / "csgo"
    inventory = deploy(
        mode=mode,
        plan=plan,
        csgo_root=csgo_root,
        state_root=state_root,
        inventory_path=state_root / "runtime" / "mode-inventory.json",
    )
    if env_path is not None:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(
            "".join(f"{key}={value}\n" for key, value in env_values.items()), encoding="utf-8"
        )
    return inventory


def verify_mode(**kwargs: Any) -> dict[str, Any]:
    plan, manifest = build_plan(**kwargs)
    return {
        "mode": manifest["id"],
        "files": len(plan),
        "plugins": [plugin["name"] for plugin in manifest.get("plugins", [])],
    }


def cleanup_managed(server_root: Path, state_root: Path) -> None:
    csgo_root = server_root / "game" / "csgo"
    inventory_path = state_root / "runtime" / "mode-inventory.json"
    previous, _ = _inventory_files(inventory_path, csgo_root)
    for relative in sorted(previous, reverse=True):
        target = _inside(csgo_root, _relative(relative, "inventory path"))
        target.unlink(missing_ok=True)
        _remove_empty_parents(target, csgo_root)
    inventory_path.unlink(missing_ok=True)


def sync_config(
    *, modes_root: Path, server_root: Path, state_root: Path, mode: str, name: str
) -> Path:
    _, manifest = load_manifest(modes_root, mode)
    config = next(
        (row for row in manifest.get("configs", []) if isinstance(row, dict) and row.get("name") == name),
        None,
    )
    if config is None:
        raise ModeError(f"unknown config {name!r} for mode {mode}")
    if config.get("editable", True) is False:
        raise ModeError(f"config {name!r} is owned by the upstream {mode} release")
    target_rel = _relative(config["target"], "config target")
    override = state_root / "configs" / mode / Path(*target_rel.parts)
    if not override.is_file() or override.is_symlink():
        raise ModeError(f"config override is missing: {override}")
    inventory_path = state_root / "runtime" / "mode-inventory.json"
    inventory = _read_json(inventory_path)
    if inventory.get("version") != 2 or inventory.get("mode") != mode:
        raise ModeError(f"mode {mode} is not active")
    rows = inventory.get("files", [])
    row = next((item for item in rows if item.get("path") == target_rel.as_posix()), None)
    if row is None:
        raise ModeError(f"config target is not managed: {target_rel}")
    destination = _inside(server_root / "game" / "csgo", target_rel)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(handle)
    try:
        shutil.copy2(override, temporary)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    row["sha256"] = _sha256(destination)
    row["source"] = str(override)
    inventory["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(inventory_path, inventory)
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes-root", type=Path, required=True)
    parser.add_argument("--server-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--server-config", type=Path)
    parser.add_argument("--versions", type=Path)
    parser.add_argument("--installed-versions", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--state", type=Path)
    apply.add_argument("--env", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("mode")
    commands.add_parser("cleanup")
    sync = commands.add_parser("sync-config")
    sync.add_argument("mode")
    sync.add_argument("name")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "cleanup":
            cleanup_managed(args.server_root, args.state_root)
            print("managed mode files removed")
            return 0
        if args.command == "sync-config":
            path = sync_config(
                modes_root=args.modes_root,
                server_root=args.server_root,
                state_root=args.state_root,
                mode=args.mode,
                name=args.name,
            )
            print(path)
            return 0
        required = (args.server_config, args.versions, args.installed_versions)
        if any(path is None for path in required):
            raise ModeError("server-config, versions, and installed-versions are required")
        common = {
            "modes_root": args.modes_root,
            "server_root": args.server_root,
            "state_root": args.state_root,
            "server_config": args.server_config,
            "versions_path": args.versions,
            "installed_versions_path": args.installed_versions,
        }
        if args.command == "verify":
            print(json.dumps(verify_mode(mode=args.mode, **common), indent=2))
        else:
            state = args.state or args.state_root / "runtime" / "active-mode.json"
            print(json.dumps(apply_mode(state_path=state, env_path=args.env, **common), indent=2))
        return 0
    except ModeError as exc:
        print(f"mode-manager: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
