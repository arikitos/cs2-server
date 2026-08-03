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
FORMAT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
MAP_NAME_RE = re.compile(r"^[a-z0-9_]+$")
ARG_HINT_RE = re.compile(r"^<[a-z][a-z_ ]*>$")
JSON_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
CONFIG_VALUE_RE = re.compile(r"^[A-Za-z0-9_.@/ -]*$")

# Panel-editable settings. 'map' and 'capacity' are no longer stored: they are
# derived from map_pool[0] and from the selected match format.
SETTING_FIELDS = (
    "format", "map_pool", "max_rounds", "freezetime", "warmup_time",
    "round_time", "bot_quota", "friendly_fire", "overtime", "overtime_max_rounds",
)
FRIENDLY_FIRE_MODES = ("off", "nades", "regular")
ACTION_GROUPS = ("match", "practice", "teams", "bots", "server", "map", "readonly", "plugin")
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
_SETTINGS_KEYS = {"formats", "defaults", "extra_cfg", "note"}
_FORMAT_KEYS = {
    "key", "label", "detail", "capacity", "team_size", "game_alias",
    "default", "cfg", "plugin_config", "note",
}
_PLUGIN_CONFIG_KEYS = {"config", "set", "note"}
_PLUGIN_KEYS = {"name", "role", "verify", "mounts", "build", "note"}
_BUILD_KEYS = {"project", "shared", "note"}
_VERIFY_KEYS = {"required", "aliases", "note"}
_MOUNT_KEYS = {"source", "target", "kind", "shared", "absolute", "note"}
_CONFIG_KEYS = {"name", "source", "target", "kind", "shared", "absolute", "note"}
_ACTION_KEYS = {
    "key", "label", "cmd", "impact", "description", "confirm", "group", "arg_hint", "note",
}
_REQUIRES_KEYS = {"metamod", "counterstrikesharp", "note"}

ACTION_PUBLIC_FIELDS = (
    "key", "label", "cmd", "impact", "description", "confirm", "group", "arg_hint",
)
FORMAT_PUBLIC_FIELDS = ("key", "label", "detail", "capacity", "team_size", "game_alias")


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


def _num(container: dict, key: str, where: str, lo: float, hi: float,
         default: float | None = None) -> float:
    if key not in container:
        if default is not None:
            return default
        raise DefinitionError(f"{where}: missing '{key}'")
    value = container[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DefinitionError(f"{where}.{key}: expected a number")
    if not lo <= value <= hi:
        raise DefinitionError(f"{where}.{key}: must be between {lo:g} and {hi:g}")
    return float(value)


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


def _convar_lines(raw: object, where: str) -> list[str]:
    if not isinstance(raw, list):
        raise DefinitionError(f"{where}: expected a list")
    lines: list[str] = []
    for index, line in enumerate(raw):
        if not isinstance(line, str) or not COMMAND_RE.fullmatch(line.strip()):
            raise DefinitionError(f"{where}[{index}]: not a plain convar line")
        lines.append(line.strip())
    return lines


def _plugin_config(raw: object, where: str, config_names: set[str]) -> dict:
    entry = _obj(raw, _PLUGIN_CONFIG_KEYS, where)
    name = _str(entry, "config", where)
    if name not in config_names:
        raise DefinitionError(f"{where}.config: {name!r} is not a declared config of this mode")
    assignments = entry.get("set")
    if not isinstance(assignments, dict) or not assignments:
        raise DefinitionError(f"{where}.set: expected a non-empty object of JSON paths")
    values: dict[str, object] = {}
    for path, value in assignments.items():
        if not isinstance(path, str) or not JSON_PATH_RE.fullmatch(path):
            raise DefinitionError(f"{where}.set: {path!r} is not a dotted JSON path")
        if isinstance(value, bool) or isinstance(value, (int, float)):
            values[path] = value
        elif isinstance(value, str) and CONFIG_VALUE_RE.fullmatch(value):
            values[path] = value
        else:
            raise DefinitionError(f"{where}.set.{path}: expected a number, boolean or plain string")
    return {"config": name, "set": values}


def _format(raw: object, where: str, fallback_alias: str, config_names: set[str]) -> dict:
    entry = _obj(raw, _FORMAT_KEYS, where)
    key = _str(entry, "key", where, FORMAT_KEY_RE)
    capacity = _int(entry, "capacity", where, 1, 64)
    team_size = _int(entry, "team_size", where, 1, 32)
    alias = _str(entry, "game_alias", where, default=fallback_alias)
    if alias not in GAME_ALIASES:
        raise DefinitionError(f"{where}.game_alias: expected one of {', '.join(GAME_ALIASES)}")
    return {
        "key": key,
        "label": _str(entry, "label", where),
        "detail": _str(entry, "detail", where, default=""),
        "capacity": capacity,
        "team_size": team_size,
        "game_alias": alias,
        "default": _bool(entry, "default", where, default=False),
        "cfg": _convar_lines(entry.get("cfg", []), f"{where}.cfg"),
        "plugin_config": (
            _plugin_config(entry["plugin_config"], f"{where}.plugin_config", config_names)
            if "plugin_config" in entry else None
        ),
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
    config_names = {config["name"] for config in configs}

    settings_raw = _obj(doc.get("settings"), _SETTINGS_KEYS, f"{where}.settings")
    formats_raw = settings_raw.get("formats")
    if not isinstance(formats_raw, list) or not formats_raw:
        raise DefinitionError(f"{where}.settings.formats: expected a non-empty list")
    formats, seen_formats = [], set()
    for index, item in enumerate(formats_raw):
        entry = _format(
            item, f"{where}.settings.formats[{index}]", game_alias, config_names,
        )
        if entry["key"] in seen_formats:
            raise DefinitionError(
                f"{where}.settings.formats[{index}].key: declared twice"
            )
        seen_formats.add(entry["key"])
        formats.append(entry)
    if sum(1 for entry in formats if entry["default"]) > 1:
        raise DefinitionError(f"{where}.settings.formats: more than one default format")

    defaults_raw = _obj(
        settings_raw.get("defaults"), set(SETTING_FIELDS) | {"note"},
        f"{where}.settings.defaults",
    )
    missing = [field for field in SETTING_FIELDS if field not in defaults_raw]
    if missing:
        raise DefinitionError(f"{where}.settings.defaults: missing {', '.join(missing)}")
    default_format = _str(
        defaults_raw, "format", f"{where}.settings.defaults", FORMAT_KEY_RE,
    )
    if default_format not in seen_formats:
        raise DefinitionError(
            f"{where}.settings.defaults.format: {default_format!r} is not a declared format"
        )
    pool_raw = defaults_raw.get("map_pool")
    if not isinstance(pool_raw, list) or not pool_raw:
        raise DefinitionError(f"{where}.settings.defaults.map_pool: expected a non-empty list")
    map_pool: list[str] = []
    for index, name in enumerate(pool_raw):
        if not isinstance(name, str) or not MAP_NAME_RE.fullmatch(name):
            raise DefinitionError(f"{where}.settings.defaults.map_pool[{index}]: invalid map name")
        if name not in map_pool:
            map_pool.append(name)
    friendly_fire = _str(defaults_raw, "friendly_fire", f"{where}.settings.defaults")
    if friendly_fire not in FRIENDLY_FIRE_MODES:
        raise DefinitionError(
            f"{where}.settings.defaults.friendly_fire: expected one of "
            f"{', '.join(FRIENDLY_FIRE_MODES)}"
        )
    spot = f"{where}.settings.defaults"
    defaults = {
        "format": default_format,
        "map_pool": map_pool,
        "max_rounds": _int(defaults_raw, "max_rounds", spot, 1, 120),
        "freezetime": _int(defaults_raw, "freezetime", spot, 0, 60),
        "warmup_time": _int(defaults_raw, "warmup_time", spot, 0, 600),
        "round_time": _num(defaults_raw, "round_time", spot, 0.5, 60),
        "bot_quota": _int(defaults_raw, "bot_quota", spot, 0, 10),
        "friendly_fire": friendly_fire,
        "overtime": _bool(defaults_raw, "overtime", spot),
        "overtime_max_rounds": _int(defaults_raw, "overtime_max_rounds", spot, 2, 30),
    }
    extra_cfg = _convar_lines(
        settings_raw.get("extra_cfg", []), f"{where}.settings.extra_cfg",
    )

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
        group = _str(entry, "group", spot, default="match")
        if group not in ACTION_GROUPS:
            raise DefinitionError(f"{spot}.group: expected one of {', '.join(ACTION_GROUPS)}")
        actions.append({
            "key": key,
            "label": _str(entry, "label", spot),
            "cmd": _str(entry, "cmd", spot, COMMAND_RE),
            "impact": _str(entry, "impact", spot),
            "description": _str(entry, "description", spot),
            "confirm": _bool(entry, "confirm", spot, default=True),
            "group": group,
            "arg_hint": _str(entry, "arg_hint", spot, ARG_HINT_RE, default=""),
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
        "capacity": {
            "min": min(entry["capacity"] for entry in formats),
            "max": max(entry["capacity"] for entry in formats),
        },
        "formats": formats,
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
