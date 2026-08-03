"""Validated declarative definitions for the single-runtime CS2 manager."""

from __future__ import annotations

import json
import re
from pathlib import Path

MODE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
CFG_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.cfg$")
ACTION_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")
COMMAND_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?: [A-Za-z0-9_.\-]+)*$")

SETTING_FIELDS = ("map", "capacity", "max_rounds", "freezetime", "friendly_fire", "bot_quota")
GAME_ALIASES = ("competitive", "casual", "wingman", "deathmatch")
TARGET_PREFIXES = ("addons/", "cfg/")
ABSOLUTE_TARGET_PREFIX = "/addons/"
RESERVED_RELATIVE_TARGETS = {
    "addons", "addons/counterstrikesharp", "addons/counterstrikesharp/plugins",
    "addons/counterstrikesharp/shared", "addons/counterstrikesharp/configs",
    "addons/metamod", "cfg",
}
RESERVED_ABSOLUTE_TARGETS = {"/addons"}

_TOP_KEYS = {
    "id", "label", "implementation", "order", "server_config", "startup",
    "settings", "plugins", "configs", "actions", "requires", "note",
}
_STARTUP_KEYS = {"game_alias", "mode_cfg", "runtime_cfg", "note"}
_SETTINGS_KEYS = {"capacity", "defaults", "extra_cfg", "note"}
_PLUGIN_KEYS = {"name", "role", "verify", "mounts", "build", "note"}
_BUILD_KEYS = {"project", "shared", "note"}
_VERIFY_KEYS = {"required", "aliases", "note"}
_MOUNT_KEYS = {"source", "target", "kind", "shared", "absolute", "note"}
_CONFIG_KEYS = {"name", "source", "target", "kind", "shared", "absolute", "note"}
_ACTION_KEYS = {"key", "label", "cmd", "impact", "description", "confirm", "note"}
_REQUIRES_KEYS = {"metamod", "counterstrikesharp", "note"}

ACTION_PUBLIC_FIELDS = ("key", "label", "cmd", "impact", "description", "confirm")


class DefinitionError(ValueError):
    """A mode manifest failed validation."""


def _obj(value: object, allowed: set[str], where: str) -> dict:
    if not isinstance(value, dict):
        raise DefinitionError(f"{where}: expected an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DefinitionError(f"{where}: unknown key(s) {', '.join(unknown)}")
    return value


def _str(container: dict, key: str, where: str, pattern: re.Pattern | None = None,
         default: str | None = None) -> str:
    if key not in container:
        if default is not None:
            return default
        raise DefinitionError(f"{where}: missing '{key}'")
    value = container[key]
    if not isinstance(value, str) or not value.strip():
        raise DefinitionError(f"{where}.{key}: expected a non-empty string")
    value = value.strip()
    if pattern and not pattern.fullmatch(value):
        raise DefinitionError(f"{where}.{key}: {value!r} is not an allowed value")
    return value


def _int(container: dict, key: str, where: str, lo: int, hi: int,
         default: int | None = None) -> int:
    if key not in container:
        if default is not None:
            return default
        raise DefinitionError(f"{where}: missing '{key}'")
    value = container[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise DefinitionError(f"{where}.{key}: expected an integer")
    if not lo <= value <= hi:
        raise DefinitionError(f"{where}.{key}: must be between {lo} and {hi}")
    return value


def _bool(container: dict, key: str, where: str, default: bool | None = None) -> bool:
    if key not in container:
        if default is None:
            raise DefinitionError(f"{where}: missing '{key}'")
        return default
    if not isinstance(container[key], bool):
        raise DefinitionError(f"{where}.{key}: expected true or false")
    return container[key]


def _relative_source(raw: str, where: str, field: str = "source") -> str:
    if raw.startswith("/") or "\\" in raw or ":" in raw:
        raise DefinitionError(f"{where}.{field}: must be a relative POSIX path")
    parts = raw.split("/")
    if any(part in ("", ".", "..") or not NAME_RE.fullmatch(part) for part in parts):
        raise DefinitionError(f"{where}.{field}: {raw!r} contains an unsafe path segment")
    return raw


def _mount(raw: object, where: str, allowed: set[str] = _MOUNT_KEYS) -> dict:
    entry = _obj(raw, allowed, where)
    source = _relative_source(_str(entry, "source", where), where)
    absolute = _bool(entry, "absolute", where, default=False)
    target = _str(entry, "target", where)
    if "\\" in target:
        raise DefinitionError(f"{where}.target: contains an unsafe path segment")
    parts = target.lstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise DefinitionError(f"{where}.target: contains an unsafe path segment")
    if absolute:
        if not target.startswith(ABSOLUTE_TARGET_PREFIX):
            raise DefinitionError(
                f"{where}.target: an absolute target must start with {ABSOLUTE_TARGET_PREFIX}"
            )
        if target.rstrip("/") in RESERVED_ABSOLUTE_TARGETS:
            raise DefinitionError(f"{where}.target: reserved framework root")
    else:
        if not target.startswith(TARGET_PREFIXES):
            raise DefinitionError(
                f"{where}.target: must start with one of {', '.join(TARGET_PREFIXES)} "
                f"or set absolute=true"
            )
        if target.rstrip("/") in RESERVED_RELATIVE_TARGETS:
            raise DefinitionError(f"{where}.target: reserved framework root")
    kind = _str(entry, "kind", where, default="dir")
    if kind not in ("dir", "file"):
        raise DefinitionError(f"{where}.kind: expected 'dir' or 'file'")
    return {
        "source": source,
        "target": target,
        "kind": kind,
        "shared": _bool(entry, "shared", where, default=False),
        "absolute": absolute,
    }


def parse_definition(raw: object, mode_id: str) -> dict:
    where = f"modes/{mode_id}/mode.json"
    doc = _obj(raw, _TOP_KEYS, where)
    declared = _str(doc, "id", where, MODE_ID_RE)
    if declared != mode_id:
        raise DefinitionError(f"{where}.id: {declared!r} does not match its directory")

    startup_raw = _obj(doc.get("startup"), _STARTUP_KEYS, f"{where}.startup")
    game_alias = _str(startup_raw, "game_alias", f"{where}.startup")
    if game_alias not in GAME_ALIASES:
        raise DefinitionError(
            f"{where}.startup.game_alias: expected one of {', '.join(GAME_ALIASES)}"
        )

    settings_raw = _obj(doc.get("settings"), _SETTINGS_KEYS, f"{where}.settings")
    cap_raw = _obj(
        settings_raw.get("capacity"), {"min", "max", "note"},
        f"{where}.settings.capacity",
    )
    cap_min = _int(cap_raw, "min", f"{where}.settings.capacity", 1, 64)
    cap_max = _int(cap_raw, "max", f"{where}.settings.capacity", 1, 64)
    if cap_min > cap_max:
        raise DefinitionError(f"{where}.settings.capacity: min is greater than max")

    defaults_raw = _obj(
        settings_raw.get("defaults"), set(SETTING_FIELDS) | {"note"},
        f"{where}.settings.defaults",
    )
    missing = [field for field in SETTING_FIELDS if field not in defaults_raw]
    if missing:
        raise DefinitionError(f"{where}.settings.defaults: missing {', '.join(missing)}")
    defaults = {
        "map": _str(
            defaults_raw, "map", f"{where}.settings.defaults",
            re.compile(r"^[a-z0-9_]+$"),
        ),
        "capacity": _int(
            defaults_raw, "capacity", f"{where}.settings.defaults", cap_min, cap_max,
        ),
        "max_rounds": _int(
            defaults_raw, "max_rounds", f"{where}.settings.defaults", 1, 120,
        ),
        "freezetime": _int(
            defaults_raw, "freezetime", f"{where}.settings.defaults", 0, 60,
        ),
        "bot_quota": _int(
            defaults_raw, "bot_quota", f"{where}.settings.defaults", 0, 10,
        ),
        "friendly_fire": _bool(
            defaults_raw, "friendly_fire", f"{where}.settings.defaults",
        ),
    }

    extra_raw = settings_raw.get("extra_cfg", [])
    if not isinstance(extra_raw, list):
        raise DefinitionError(f"{where}.settings.extra_cfg: expected a list")
    extra_cfg: list[str] = []
    for index, line in enumerate(extra_raw):
        if not isinstance(line, str) or not COMMAND_RE.fullmatch(line.strip()):
            raise DefinitionError(
                f"{where}.settings.extra_cfg[{index}]: not a plain convar line"
            )
        extra_cfg.append(line.strip())

    plugins_raw = doc.get("plugins")
    if not isinstance(plugins_raw, list) or not plugins_raw:
        raise DefinitionError(f"{where}.plugins: expected a non-empty list")
    plugins, seen_names = [], set()
    for index, item in enumerate(plugins_raw):
        spot = f"{where}.plugins[{index}]"
        entry = _obj(item, _PLUGIN_KEYS, spot)
        name = _str(entry, "name", spot, NAME_RE)
        if name in seen_names:
            raise DefinitionError(f"{spot}.name: declared twice")
        seen_names.add(name)
        role = _str(entry, "role", spot)
        if role not in ("plugin", "util"):
            raise DefinitionError(f"{spot}.role: expected plugin or util")
        verify = _obj(entry.get("verify", {}), _VERIFY_KEYS, f"{spot}.verify")
        aliases_raw = verify.get("aliases", [])
        if not isinstance(aliases_raw, list):
            raise DefinitionError(f"{spot}.verify.aliases: expected a list")
        aliases = []
        for alias in aliases_raw:
            if not isinstance(alias, str) or not alias.strip():
                raise DefinitionError(f"{spot}.verify.aliases: expected strings")
            aliases.append(alias.strip().lower())
        mounts_raw = entry.get("mounts")
        if not isinstance(mounts_raw, list) or not mounts_raw:
            raise DefinitionError(f"{spot}.mounts: expected a non-empty list")
        build = None
        if "build" in entry:
            build_raw = _obj(entry["build"], _BUILD_KEYS, f"{spot}.build")
            build = {
                "project": _relative_source(
                    _str(build_raw, "project", f"{spot}.build"),
                    f"{spot}.build", "project",
                ),
                "shared": _bool(build_raw, "shared", f"{spot}.build", default=False),
            }
        plugins.append({
            "name": name,
            "role": role,
            "required": _bool(verify, "required", f"{spot}.verify", default=False),
            "build": build,
            "aliases": aliases or [name.lower()],
            "mounts": [
                _mount(mount, f"{spot}.mounts[{mount_index}]")
                for mount_index, mount in enumerate(mounts_raw)
            ],
        })
    if not any(plugin["role"] == "plugin" for plugin in plugins):
        raise DefinitionError(f"{where}.plugins: no main plugin declared")

    configs_raw = doc.get("configs", [])
    if not isinstance(configs_raw, list):
        raise DefinitionError(f"{where}.configs: expected a list")
    configs = []
    for index, item in enumerate(configs_raw):
        spot = f"{where}.configs[{index}]"
        config_obj = _obj(item, _CONFIG_KEYS, spot)
        mount = _mount(config_obj, spot, _CONFIG_KEYS)
        mount["name"] = _str(config_obj, "name", spot)
        configs.append(mount)

    actions_raw = doc.get("actions", [])
    if not isinstance(actions_raw, list):
        raise DefinitionError(f"{where}.actions: expected a list")
    actions, seen_keys = [], set()
    for index, item in enumerate(actions_raw):
        spot = f"{where}.actions[{index}]"
        entry = _obj(item, _ACTION_KEYS, spot)
        key = _str(entry, "key", spot, ACTION_KEY_RE)
        if key in seen_keys:
            raise DefinitionError(f"{spot}.key: declared twice")
        seen_keys.add(key)
        actions.append({
            "key": key,
            "label": _str(entry, "label", spot),
            "cmd": _str(entry, "cmd", spot, COMMAND_RE),
            "impact": _str(entry, "impact", spot),
            "description": _str(entry, "description", spot),
            "confirm": _bool(entry, "confirm", spot, default=True),
        })

    requires_raw = _obj(doc.get("requires"), _REQUIRES_KEYS, f"{where}.requires")
    requires = {
        key: _str(requires_raw, key, f"{where}.requires", VERSION_RE)
        for key in ("metamod", "counterstrikesharp")
    }

    return {
        "id": mode_id,
        "label": _str(doc, "label", where),
        "implementation": _str(doc, "implementation", where),
        "order": _int(doc, "order", where, 0, 10_000, default=1000),
        "server_config": _bool(doc, "server_config", where, default=True),
        "startup": {
            "game_alias": game_alias,
            "mode_cfg": _str(
                startup_raw, "mode_cfg", f"{where}.startup", CFG_FILE_RE,
            ),
            "runtime_cfg": _str(
                startup_raw, "runtime_cfg", f"{where}.startup", CFG_FILE_RE,
            ),
        },
        "capacity": {"min": cap_min, "max": cap_max},
        "defaults": defaults,
        "extra_cfg": extra_cfg,
        "plugins": plugins,
        "configs": configs,
        "actions": actions,
        "requires": requires,
        "required_plugins": [plugin["name"] for plugin in plugins if plugin["required"]],
        "plugin_aliases": {plugin["name"]: plugin["aliases"] for plugin in plugins},
    }


def load_definitions(modes_root: Path) -> tuple[dict[str, dict], list[str]]:
    definitions: dict[str, dict] = {}
    errors: list[str] = []
    try:
        candidates = sorted(path for path in modes_root.iterdir() if path.is_dir())
    except OSError as exc:
        return {}, [f"modes directory unreadable ({modes_root}): {exc}"]
    for mode_dir in candidates:
        manifest = mode_dir / "mode.json"
        if not manifest.is_file():
            continue
        if not MODE_ID_RE.fullmatch(mode_dir.name):
            errors.append(f"modes/{mode_dir.name}: invalid mode directory name")
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            definitions[mode_dir.name] = parse_definition(raw, mode_dir.name)
        except (OSError, json.JSONDecodeError, DefinitionError) as exc:
            errors.append(f"modes/{mode_dir.name}/mode.json: {exc}")
    ordered = dict(sorted(definitions.items(), key=lambda item: (item[1]["order"], item[0])))
    return ordered, errors


def declared_mounts(definition: dict) -> list[dict]:
    rows: list[dict] = []
    for plugin in definition["plugins"]:
        for mount in plugin["mounts"]:
            rows.append({"owner": plugin["name"], "role": plugin["role"], **mount})
    for config in definition["configs"]:
        rows.append({
            "owner": config["name"],
            "role": "config",
            **{key: value for key, value in config.items() if key != "name"},
        })
    return rows


def mount_source_path(mount: dict, mode_dir: Path, shared_dir: Path) -> Path:
    root = shared_dir if mount.get("shared") else mode_dir
    return root.joinpath(*mount["source"].split("/"))


def build_project_path(build: dict, mode_dir: Path, shared_dir: Path) -> Path:
    root = shared_dir if build.get("shared") else mode_dir
    return root.joinpath(*build["project"].split("/"))
