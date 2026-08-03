"""Declarative mode definitions — manager/modes/<mode-id>/mode.json.

Each mode owns exactly one manifest that names its container, its startup cfgs,
its settings defaults and every plugin / config bind mount it needs. The panel
derives its mode registry, plugin verification and mount checks from these files,
so adding a plugin to a mode is a data change in that mode's manifest plus the
matching bind mount in compose.yml — never panel code.

Layout the manifests describe (Implement.md sections 10, 12, 13 and 15, applied
to this project's existing profile-per-mode structure):

    manager/modes/<mode-id>/
      mode.json                 this manifest
      cfg/                      mode_<id>.cfg + panel_runtime.cfg (+ plugin cfg trees)
      config/                   plugin config files the panel edits
      plugins/<Main>/           the plugin that defines the mode
      utils/<Helper>/           every supporting plugin / shared library of that mode
      utils/<Helper>.src/       C# source of a helper built in-house, next to (never
                                inside) the folder that is bind-mounted as the live
                                plugin, so build output stays out of the server tree

Loading is deliberately fault tolerant in two ways:

  * A missing or empty modes directory yields an empty registry instead of an
    exception, because the panel-rebuild health check imports app.py in a
    container that has no /modes mount.
  * One invalid manifest is skipped and reported through `errors` rather than
    taking the whole panel down; /api/v3/health and verify-mounts surface it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MODE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
CFG_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.cfg$")
ACTION_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
# Console/cfg safety: a single command plus plain arguments. No quotes, newlines,
# semicolons or shell metacharacters can reach a generated cfg or an RCON send.
COMMAND_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?: [A-Za-z0-9_.\-]+)*$")

SETTING_FIELDS = ("map", "capacity", "max_rounds", "freezetime", "friendly_fire", "bot_quota")
GAME_ALIASES = ("competitive", "casual", "wingman", "deathmatch")

# Bind-mount targets are relative to the container's game/csgo directory, with one
# documented exception (RayTrace's absolute /addons path, see the heroshift
# manifest), which must be declared with "absolute": true.
TARGET_PREFIXES = ("addons/", "cfg/")
ABSOLUTE_TARGET_PREFIX = "/addons/"

_TOP_KEYS = {"id", "label", "implementation", "order", "container", "capacity_env",
             "server_config", "startup", "settings", "plugins", "configs", "actions",
             "note"}
_STARTUP_KEYS = {"game_alias", "mode_cfg", "runtime_cfg", "note"}
_SETTINGS_KEYS = {"capacity", "defaults", "extra_cfg", "note"}
_PLUGIN_KEYS = {"name", "role", "verify", "mounts", "build", "note"}
_BUILD_KEYS = {"project", "shared", "note"}
_VERIFY_KEYS = {"required", "aliases", "note"}
_MOUNT_KEYS = {"source", "target", "kind", "shared", "absolute", "note"}
_CONFIG_KEYS = {"name", "source", "target", "kind", "shared", "absolute", "note"}
_ACTION_KEYS = {"key", "label", "cmd", "impact", "description", "confirm", "note"}

ACTION_PUBLIC_FIELDS = ("key", "label", "cmd", "impact", "description", "confirm")


class DefinitionError(ValueError):
    """A mode.json failed validation. Message is safe to show in the panel."""


# --------------------------------------------------------------------------- #
# Small typed readers — every one raises DefinitionError with a precise message
# --------------------------------------------------------------------------- #
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
    if absolute:
        if not target.startswith(ABSOLUTE_TARGET_PREFIX):
            raise DefinitionError(
                f"{where}.target: an absolute target must start with {ABSOLUTE_TARGET_PREFIX}")
    elif not target.startswith(TARGET_PREFIXES):
        raise DefinitionError(
            f"{where}.target: must start with one of {', '.join(TARGET_PREFIXES)} "
            f"(relative to game/csgo), or set \"absolute\": true")
    if ".." in target.split("/"):
        raise DefinitionError(f"{where}.target: must not contain '..'")
    kind = _str(entry, "kind", where, default="dir")
    if kind not in ("dir", "file"):
        raise DefinitionError(f"{where}.kind: expected 'dir' or 'file'")
    return {
        "source": source,
        "target": target,
        "kind": kind,
        # Shared sources resolve under manager/shared/ instead of the mode dir;
        # PanelBridge is the single shared copy every mode declares.
        "shared": _bool(entry, "shared", where, default=False),
        "absolute": absolute,
    }


# --------------------------------------------------------------------------- #
# Manifest parsing
# --------------------------------------------------------------------------- #
def parse_definition(raw: object, mode_id: str) -> dict:
    """Validate one manifest and return the normalized definition."""
    where = f"modes/{mode_id}/mode.json"
    doc = _obj(raw, _TOP_KEYS, where)

    declared = _str(doc, "id", where, MODE_ID_RE)
    if declared != mode_id:
        raise DefinitionError(f"{where}.id: {declared!r} does not match its directory {mode_id!r}")

    startup_raw = _obj(doc.get("startup"), _STARTUP_KEYS, f"{where}.startup")
    game_alias = _str(startup_raw, "game_alias", f"{where}.startup")
    if game_alias not in GAME_ALIASES:
        raise DefinitionError(
            f"{where}.startup.game_alias: expected one of {', '.join(GAME_ALIASES)}")

    settings_raw = _obj(doc.get("settings"), _SETTINGS_KEYS, f"{where}.settings")
    cap_raw = _obj(settings_raw.get("capacity"), {"min", "max", "note"}, f"{where}.settings.capacity")
    cap_min = _int(cap_raw, "min", f"{where}.settings.capacity", 1, 64)
    cap_max = _int(cap_raw, "max", f"{where}.settings.capacity", 1, 64)
    if cap_min > cap_max:
        raise DefinitionError(f"{where}.settings.capacity: min is greater than max")

    defaults_raw = _obj(settings_raw.get("defaults"), set(SETTING_FIELDS) | {"note"},
                        f"{where}.settings.defaults")
    missing = [f for f in SETTING_FIELDS if f not in defaults_raw]
    if missing:
        raise DefinitionError(f"{where}.settings.defaults: missing {', '.join(missing)}")
    defaults = {
        "map": _str(defaults_raw, "map", f"{where}.settings.defaults",
                    re.compile(r"^[a-z0-9_]+$")),
        "capacity": _int(defaults_raw, "capacity", f"{where}.settings.defaults", cap_min, cap_max),
        "max_rounds": _int(defaults_raw, "max_rounds", f"{where}.settings.defaults", 1, 120),
        "freezetime": _int(defaults_raw, "freezetime", f"{where}.settings.defaults", 0, 60),
        "bot_quota": _int(defaults_raw, "bot_quota", f"{where}.settings.defaults", 0, 10),
        "friendly_fire": _bool(defaults_raw, "friendly_fire", f"{where}.settings.defaults"),
    }

    extra_raw = settings_raw.get("extra_cfg", [])
    if not isinstance(extra_raw, list):
        raise DefinitionError(f"{where}.settings.extra_cfg: expected a list")
    extra_cfg = []
    for index, line in enumerate(extra_raw):
        spot = f"{where}.settings.extra_cfg[{index}]"
        if not isinstance(line, str) or not COMMAND_RE.fullmatch(line.strip()):
            raise DefinitionError(f"{spot}: not a plain 'convar value' line")
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
            raise DefinitionError(f"{spot}.name: {name!r} is declared twice")
        seen_names.add(name)
        role = _str(entry, "role", spot)
        if role not in ("plugin", "util"):
            raise DefinitionError(f"{spot}.role: expected 'plugin' or 'util'")
        verify = _obj(entry.get("verify", {}), _VERIFY_KEYS, f"{spot}.verify")
        aliases_raw = verify.get("aliases", [])
        if not isinstance(aliases_raw, list):
            raise DefinitionError(f"{spot}.verify.aliases: expected a list")
        aliases = []
        for alias in aliases_raw:
            if not isinstance(alias, str) or not alias.strip():
                raise DefinitionError(f"{spot}.verify.aliases: expected non-empty strings")
            aliases.append(alias.strip().lower())
        mounts_raw = entry.get("mounts")
        if not isinstance(mounts_raw, list) or not mounts_raw:
            raise DefinitionError(f"{spot}.mounts: expected a non-empty list")
        # Plugins built in-house name their C# project here. It is never mounted
        # into the container — only recorded, so the panel can check it is present
        # and the manifest stays the single place a util's provenance is written.
        build = None
        if "build" in entry:
            build_raw = _obj(entry["build"], _BUILD_KEYS, f"{spot}.build")
            build = {
                "project": _relative_source(
                    _str(build_raw, "project", f"{spot}.build"), f"{spot}.build", "project"),
                "shared": _bool(build_raw, "shared", f"{spot}.build", default=False),
            }
        plugins.append({
            "name": name,
            "role": role,
            "required": _bool(verify, "required", f"{spot}.verify", default=False),
            "build": build,
            # `css_plugins list` / `meta list` report display names, not folder
            # names, so verification matches on tolerant lowercase aliases.
            "aliases": aliases or [name.lower()],
            "mounts": [_mount(m, f"{spot}.mounts[{i}]") for i, m in enumerate(mounts_raw)],
        })
    if not any(p["role"] == "plugin" for p in plugins):
        raise DefinitionError(f"{where}.plugins: no entry with role 'plugin'")

    configs_raw = doc.get("configs", [])
    if not isinstance(configs_raw, list):
        raise DefinitionError(f"{where}.configs: expected a list")
    configs = []
    for index, item in enumerate(configs_raw):
        spot = f"{where}.configs[{index}]"
        mount = _mount(item, spot, _CONFIG_KEYS)
        mount["name"] = _str(_obj(item, _CONFIG_KEYS, spot), "name", spot)
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
            raise DefinitionError(f"{spot}.key: {key!r} is declared twice")
        seen_keys.add(key)
        actions.append({
            "key": key,
            "label": _str(entry, "label", spot),
            # Whitelisted RCON command for this action — never UI-supplied text.
            "cmd": _str(entry, "cmd", spot, COMMAND_RE),
            "impact": _str(entry, "impact", spot),
            "description": _str(entry, "description", spot),
            "confirm": _bool(entry, "confirm", spot, default=True),
        })

    return {
        "id": mode_id,
        "label": _str(doc, "label", where),
        "implementation": _str(doc, "implementation", where),
        "order": _int(doc, "order", where, 0, 10_000, default=1000),
        "container": _str(doc, "container", where, CONTAINER_RE),
        "capacity_env": _str(doc, "capacity_env", where, ENV_NAME_RE),
        # Whether the panel shows its generic Server Config card for this mode.
        # Modes that own their settings elsewhere set this to false.
        "server_config": _bool(doc, "server_config", where, default=True),
        "startup": {
            "game_alias": game_alias,
            "mode_cfg": _str(startup_raw, "mode_cfg", f"{where}.startup", CFG_FILE_RE),
            "runtime_cfg": _str(startup_raw, "runtime_cfg", f"{where}.startup", CFG_FILE_RE),
        },
        "capacity": {"min": cap_min, "max": cap_max},
        "defaults": defaults,
        "extra_cfg": extra_cfg,
        "plugins": plugins,
        "configs": configs,
        "actions": actions,
        "required_plugins": [p["name"] for p in plugins if p["required"]],
        "plugin_aliases": {p["name"]: p["aliases"] for p in plugins},
    }


def load_definitions(modes_root: Path) -> tuple[dict[str, dict], list[str]]:
    """Load every manager/modes/<id>/mode.json.

    Returns (definitions ordered by `order` then id, error messages). Never
    raises: a missing directory gives an empty registry, and an invalid manifest
    is skipped and reported.
    """
    definitions: dict[str, dict] = {}
    errors: list[str] = []
    try:
        candidates = sorted(p for p in modes_root.iterdir() if p.is_dir())
    except OSError as exc:
        return {}, [f"modes directory unreadable ({modes_root}): {exc}"]

    for mode_dir in candidates:
        manifest = mode_dir / "mode.json"
        if not manifest.is_file():
            continue
        if not MODE_ID_RE.fullmatch(mode_dir.name):
            errors.append(f"modes/{mode_dir.name}: directory name is not a valid mode id")
            continue
        try:
            definitions[mode_dir.name] = parse_definition(
                json.loads(manifest.read_text(encoding="utf-8")), mode_dir.name)
        except (OSError, json.JSONDecodeError, DefinitionError) as exc:
            errors.append(f"modes/{mode_dir.name}/mode.json: {exc}")

    containers: dict[str, str] = {}
    for mode_id, definition in list(definitions.items()):
        clash = containers.get(definition["container"])
        if clash:
            errors.append(f"modes/{mode_id}/mode.json: container "
                          f"{definition['container']!r} is already used by {clash!r}")
            definitions.pop(mode_id)
            continue
        containers[definition["container"]] = mode_id

    ordered = dict(sorted(definitions.items(), key=lambda kv: (kv[1]["order"], kv[0])))
    return ordered, errors


# --------------------------------------------------------------------------- #
# Helpers the panel uses to walk a definition's mounts
# --------------------------------------------------------------------------- #
def declared_mounts(definition: dict) -> list[dict]:
    """Every bind mount the mode declares, as flat {owner, role, ...mount} rows."""
    rows: list[dict] = []
    for plugin in definition["plugins"]:
        for mount in plugin["mounts"]:
            rows.append({"owner": plugin["name"], "role": plugin["role"], **mount})
    for config in definition["configs"]:
        rows.append({"owner": config["name"], "role": "config",
                     **{k: v for k, v in config.items() if k != "name"}})
    return rows


def mount_source_path(mount: dict, mode_dir: Path, shared_dir: Path) -> Path:
    """Host-side path of a declared mount source."""
    root = shared_dir if mount.get("shared") else mode_dir
    return root.joinpath(*mount["source"].split("/"))


def build_project_path(build: dict, mode_dir: Path, shared_dir: Path) -> Path:
    """Host-side path of a plugin's in-house C# project (`build.project`)."""
    root = shared_dir if build.get("shared") else mode_dir
    return root.joinpath(*build["project"].split("/"))
