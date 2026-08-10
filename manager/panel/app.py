"""CS2 Manager panel for one persistent server and one active mode."""

from __future__ import annotations

import hmac
import json
import math
import os
import re
import secrets as secrets_mod
import shutil
import socket
import struct
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Callable

import docker
from docker.errors import DockerException, NotFound
from flask import Flask, Response, has_request_context, jsonify, render_template, request

import mode_defs

app = Flask(__name__)


class _LazyDockerClient:
    _client = None

    def _get(self):
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def __getattr__(self, name):
        return getattr(self._get(), name)


client = _LazyDockerClient()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USERNAME = os.environ.get("PANEL_USERNAME", "admin")
PASSWORD = os.environ.get("PANEL_PASSWORD", "")
DATA_DIR = Path(os.environ.get("PANEL_DATA_DIR", "/data"))
MODES_ROOT = Path(os.environ.get("PANEL_MODES_DIR") or "/modes")
MODES_DIR = DATA_DIR / "modes"
RUNTIME_DIR = DATA_DIR / "runtime"
ACTIVE_MODE_JSON = RUNTIME_DIR / "active-mode.json"
AUDIT_DIR = DATA_DIR / "audit"
SERVER_JSON = DATA_DIR / "server.json"
SECRETS_JSON = DATA_DIR / "secrets.json"
CONSOLE_HISTORY_JSON = DATA_DIR / "console_history.json"

RCON_PORT = int(os.environ.get("CS2_PORT", "27015"))
RCON_PASSWORD = os.environ.get("CS2_RCON_PASSWORD", "")
RCON_APPLY_TIMEOUT = int(os.environ.get("RCON_APPLY_TIMEOUT", "90"))
LOG_TAIL_DEFAULT = int(os.environ.get("LOG_TAIL_DEFAULT", "300"))
CONSOLE_COMMAND_MAX_LENGTH = 256
SERVER_PASSWORD_MAX_LENGTH = 64
GAME_CONTAINER = os.environ.get("GAME_CONTAINER", "cs2-game")

PROJECT_DIR = Path(os.environ.get("PANEL_PROJECT_DIR", "/project"))
SERVER_DIR = Path(os.environ.get("PANEL_SERVER_DIR", "/server"))
BACKUPS_DIR = PROJECT_DIR / "backups"
SHARED_DIR = PROJECT_DIR / "shared"
VERSIONS_JSON = PROJECT_DIR / "shared/frameworks/versions.json"
CS2_DATA_PATH_HOST = os.environ.get("CS2_DATA_PATH", "")
MANAGER_PATH_HOST = os.environ.get("MANAGER_PATH", "")
UPDATER_IMAGE = os.environ.get("UPDATER_IMAGE", "cs2-manager-updater:pinned")
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "cs2-server")
UPDATER_CONFIRM_PHRASE = "UPDATE CS2"
UPDATER_CONTAINER = "cs2-updater"
PANEL_CONTAINER = "cs2-panel"

ALLOWED_MAPS = [
    item.strip().lower()
    for item in os.environ.get(
        "CS2_ALLOWED_MAPS",
        "de_ancient,de_anubis,de_dust2,de_inferno,de_mirage,de_nuke,de_overpass,de_train,de_vertigo",
    ).split(",")
    if item.strip()
]

MODE_DEFS, MODE_DEF_ERRORS = mode_defs.load_definitions(MODES_ROOT)
for _problem in MODE_DEF_ERRORS:
    app.logger.error("mode definition rejected: %s", _problem)

MODES = {
    mode: {
        "label": definition["label"],
        "implementation": definition["implementation"],
        "container": GAME_CONTAINER,
        "mode_dir": definition["id"],
        "server_config": definition["server_config"],
        "required_plugins": definition["required_plugins"],
        "requires": definition["requires"],
    }
    for mode, definition in MODE_DEFS.items()
}
MODE_ORDER = list(MODE_DEFS)
MODE_ACTIONS = {mode: definition["actions"] for mode, definition in MODE_DEFS.items()}
DEFAULT_MODE_SETTINGS = {
    mode: json.loads(json.dumps(definition["defaults"])) for mode, definition in MODE_DEFS.items()
}
CAPACITY_RANGES = {mode: dict(definition["capacity"]) for mode, definition in MODE_DEFS.items()}
MODE_FORMATS = {
    mode: {entry["key"]: entry for entry in definition["formats"]}
    for mode, definition in MODE_DEFS.items()
}
GAME_CONTAINERS = [GAME_CONTAINER]  # retained for response compatibility

# A format owns the slot count and the game alias, so it needs a fresh launch.
APPLY_LEVELS = {
    "format": "game_restart",
    "map_pool": "map_reload",
    "lan": "game_restart",
    "hostname": "hot",
    "cheats": "hot",
    "allow_lobby_connect_only": "hot",
    "limit_teams": "hot",
    "auto_team_balance": "hot",
    "spectators_max": "hot",
    "max_rounds": "hot",
    "freezetime": "hot",
    "warmup_time": "hot",
    "round_time": "hot",
    "buy_time": "hot",
    "c4_timer": "hot",
    "start_money": "hot",
    "max_money": "hot",
    "friendly_fire": "hot",
    "ff_bullet_reduction": "hot",
    "ff_grenade_reduction": "hot",
    "ff_other_reduction": "hot",
    "tk_punish": "hot",
    "bot_quota": "hot",
    "bot_quota_mode": "hot",
    "bot_difficulty": "hot",
    "bot_chatter": "hot",
    "bot_join_after_player": "hot",
    "overtime": "hot",
    "overtime_max_rounds": "hot",
}
VISIBILITY_MODES = ("public", "private")


def _cmd(key, label, cmd, impact, description, confirm=False, arg_hint=""):
    return {
        "key": key,
        "label": label,
        "cmd": cmd,
        "impact": impact,
        "description": description,
        "confirm": confirm,
        "arg_hint": arg_hint,
    }


# Commands the panel can send over RCON regardless of the active plugin set.
# "aliases" limits a group to the game alias of the selected match format.
SHARED_COMMAND_GROUPS = [
    {
        "id": "round",
        "label": "Round & match",
        "aliases": (),
        "commands": [
            _cmd("restart_game", "Restart Game", "mp_restartgame 1", "In-game round", "Restarts the game after one second.", True),
            _cmd("warmup_start", "Start Warmup", "mp_warmup_start", "In-game phase", "Puts the server back into warmup.", True),
            _cmd("warmup_end", "End Warmup", "mp_warmup_end", "In-game phase", "Ends warmup and starts the match."),
            _cmd("pause", "Pause Match", "mp_pause_match", "In-game match", "Freezes the match at the next round."),
            _cmd("unpause", "Unpause Match", "mp_unpause_match", "In-game match", "Resumes a paused match."),
        ],
    },
    {
        "id": "players",
        "label": "Players & bans",
        "aliases": (),
        "commands": [
            _cmd("status", "Server Status", "status", "Read only", "Prints players, Steam IDs, map and uptime."),
            _cmd("kick", "Kick Player", "kick", "Players", "Disconnects a player by username or userid.", True, "<username or userid>"),
            _cmd("banid", "Ban Player", "banid", "Players", "Bans a userid or SteamID for a number of minutes. Use 0 for permanent.", True, "<minutes userid or steamid>"),
            _cmd("removeid", "Remove Ban", "removeid", "Ban list", "Removes a SteamID from the ban list.", True, "<steamid>"),
            _cmd("writeid", "Save Ban List", "writeid", "Ban list", "Writes the in-memory ban list to disk.", True),
        ],
    },
    {
        "id": "bots",
        "label": "Bots",
        "aliases": (),
        "commands": [
            _cmd("bot_add", "Add Bot", "bot_add", "Players", "Adds one bot to the smaller team."),
            _cmd("bot_add_ct", "Add CT Bot", "bot_add_ct", "Players", "Adds one bot to the CT side."),
            _cmd("bot_add_t", "Add T Bot", "bot_add_t", "Players", "Adds one bot to the T side."),
            _cmd("bot_kick", "Kick All Bots", "bot_kick", "Players", "Removes every bot.", True),
            _cmd("bot_kill", "Kill All Bots", "bot_kill", "In-game round", "Kills all bots in the current round.", True),
            _cmd("bot_quota", "Set Bot Quota", "bot_quota", "Players", "Sets how many bots the server keeps filled. Append a number.", False, "<count>"),
            _cmd("bot_difficulty", "Set Bot Difficulty", "bot_difficulty", "Players", "0 easy to 3 expert. Append the level.", False, "<0-3>"),
            _cmd("bot_stop", "Freeze or Resume Bots", "bot_stop", "Players", "Use 1 to freeze bots and 0 to resume them.", False, "<0 or 1>"),
        ],
    },
    {
        "id": "live",
        "label": "Live overrides",
        "aliases": (),
        "commands": [
            _cmd("friendly_fire", "Set Friendly Fire", "mp_friendlyfire", "In-game setting", "Use 1 to enable team damage and 0 to disable it.", False, "<0 or 1>"),
            _cmd("respawn_ct", "CT Respawn", "mp_respawn_on_death_ct", "In-game setting", "Use 1 to enable immediate CT respawn and 0 to disable it.", False, "<0 or 1>"),
            _cmd("respawn_t", "T Respawn", "mp_respawn_on_death_t", "In-game setting", "Use 1 to enable immediate T respawn and 0 to disable it.", False, "<0 or 1>"),
            _cmd("buy_anywhere", "Buy Anywhere", "mp_buy_anywhere", "In-game setting", "Use 1 to buy anywhere and 0 to restore buy zones.", False, "<0 or 1>"),
        ],
    },
    {
        "id": "map",
        "label": "Map",
        "aliases": (),
        "commands": [
            _cmd("changelevel", "Change Level", "changelevel", "Map reload", "Loads a map now and disconnects nobody but interrupts the round. Append the map name.", True, "<map>"),
            _cmd("vote_nextmap_off", "Disable Next-Map Vote", "mp_endmatch_votenextmap 0", "In-game setting", "Stops the end-of-match map vote."),
            _cmd("match_end_restart", "Restart On Match End", "mp_match_end_restart 1", "In-game setting", "Restarts the same map when the match ends."),
        ],
    },
    {
        "id": "readonly",
        "label": "Read only",
        "aliases": (),
        "commands": [
            _cmd("users", "Connected Users", "users", "Read only", "Prints the connected user list."),
            _cmd("meta_list", "Metamod Plugins", "meta list", "Read only", "Lists loaded Metamod plugins."),
            _cmd("css_list", "CounterStrikeSharp Plugins", "css_plugins list", "Read only", "Lists loaded CounterStrikeSharp plugins."),
            _cmd("version", "Server Version", "version", "Read only", "Prints the build number."),
            _cmd("stats", "Server Stats", "stats", "Read only", "Prints CPU and network statistics."),
        ],
    },
]
MODE_GROUP_LABELS = {
    "match": "Match control",
    "practice": "Practice",
    "teams": "Teams",
    "map": "Map",
    "server": "Server",
    "plugin": "Plugin",
    "readonly": "Read only",
}
MODE_COMMAND_REPLACEMENTS = {
    "faceit": {"pause", "unpause"},
    "retake": {"scramble_teams"},
}


def command_catalog(mode: str | None, settings: dict | None) -> list[dict]:
    """Group every RCON command the panel offers for the given mode."""
    groups: list[dict] = []
    if mode in MODES:
        label = MODES[mode]["label"]
        actions = MODE_ACTIONS.get(mode, [])
        for group_id, group_label in MODE_GROUP_LABELS.items():
            rows = [action for action in actions if action["group"] == group_id]
            if rows:
                groups.append({
                    "id": f"{mode}_{group_id}",
                    "label": f"{label} · {group_label}",
                    "source": "plugin",
                    "commands": [
                        {key: action[key] for key in mode_defs.ACTION_PUBLIC_FIELDS if key != "group"}
                        for action in rows
                    ],
                })
    alias = (settings or {}).get("game_alias")
    if mode in MODES and not alias:
        alias = selected_format(mode, settings or {})["game_alias"]
    for group in SHARED_COMMAND_GROUPS:
        if group["aliases"] and alias not in group["aliases"]:
            continue
        replacements = MODE_COMMAND_REPLACEMENTS.get(mode, set())
        commands = [command for command in group["commands"] if command["key"] not in replacements]
        if not commands:
            continue
        groups.append({
            "id": group["id"],
            "label": group["label"],
            "source": "server",
            "commands": commands,
        })
    return groups

DEFAULT_SERVER = {
    "hostname": os.environ.get("CS2_SERVERNAME", "CS2 Server"),
    "lan": False,
    "port": RCON_PORT,
    "rcon_port": RCON_PORT,
    "friendly_fire": False,
    "cheats": False,
    "hibernate": False,
    "logging_level": "on",
    "access_mode": "public",
    "last_mode": None,
    "password_policy": "global",
}

OPERATION_LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
RCON_JOB_LOCK = threading.Lock()
RCON_JOB_GENERATION = 0
STATE_TIMESTAMPS = {
    "last_successful_start": None,
    "last_config_apply": None,
    "last_manual_update": None,
    "last_backup": None,
}

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
SECRET_PATTERNS = [
    (re.compile(r"(?i)(\+?rcon_password\s+)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(\+?sv_password\s+)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(\+sv_setsteamaccount\s+)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(SRCDS_TOKEN\s*[=:]\s*)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(CS2_RCONPW\s*[=:]\s*)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", str(text)).replace("\x00", "")
    for pattern, replacement in SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# Auth and persistence
# ---------------------------------------------------------------------------
def authorized() -> bool:
    auth = request.authorization
    return bool(
        auth
        and hmac.compare_digest(auth.username or "", USERNAME)
        and hmac.compare_digest(auth.password or "", PASSWORD)
    )


def require_auth(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not authorized():
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="CS2 Manager"'})
        return fn(*args, **kwargs)

    return wrapper


def current_user() -> str:
    auth = request.authorization
    return (auth.username if auth else "anonymous") or "anonymous"


def read_json(path: Path, default):
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(default, dict) and isinstance(stored, dict):
            merged = json.loads(json.dumps(default))
            merged.update(stored)
            return merged
        return stored
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return json.loads(json.dumps(default))


def write_json(path: Path, payload) -> None:
    with FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)


def load_server() -> dict:
    return read_json(SERVER_JSON, DEFAULT_SERVER)


def save_server(value: dict) -> None:
    write_json(SERVER_JSON, value)


def load_mode(mode: str) -> dict:
    return read_json(MODES_DIR / f"{mode}.json", DEFAULT_MODE_SETTINGS[mode])


def save_mode(mode: str, value: dict) -> None:
    write_json(MODES_DIR / f"{mode}.json", value)


def load_secrets() -> dict:
    return read_json(SECRETS_JSON, {"password_enabled": False, "server_password": "", "per_mode": {}})


def save_secrets(value: dict) -> None:
    write_json(SECRETS_JSON, value)


def audit(action: str, result: str, detail: str = "", target: str | None = None, job_id: str | None = None) -> None:
    entry = {
        "time": now_iso(),
        "user": current_user() if has_request_context() else "system",
        "role": "Owner",
        "action": action,
        "target": target,
        "result": result,
        "source_ip": request.remote_addr if has_request_context() else None,
        "detail": redact(detail)[:500],
        "job_id": job_id,
    }
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        with FILE_LOCK, (AUDIT_DIR / f"audit-{day}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        app.logger.warning("audit write failed: %s", exc)


# ---------------------------------------------------------------------------
# Modes and generated config
# ---------------------------------------------------------------------------
def mode_dir(mode: str) -> Path:
    return MODES_ROOT / MODES[mode]["mode_dir"]


def normalize_map(value: object) -> str:
    name = str(value or "").strip().lower()
    if name not in ALLOWED_MAPS or not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError("Map is not in the allowed map list")
    return name


def normalize_map_pool(value: object, fallback: list[str]) -> list[str]:
    raw = value if isinstance(value, list) else fallback
    pool: list[str] = []
    for item in raw:
        name = normalize_map(item)
        if name not in pool:
            pool.append(name)
    if not pool:
        raise ValueError("Select at least one map for the pool")
    return pool


def normalize_friendly_fire(value: object, fallback: str) -> str:
    if isinstance(value, bool):  # settings written before friendly fire had modes
        return "regular" if value else "off"
    mode = str(value or fallback).strip().lower()
    if mode not in mode_defs.FRIENDLY_FIRE_MODES:
        raise ValueError(
            "Friendly fire must be one of " + ", ".join(mode_defs.FRIENDLY_FIRE_MODES)
        )
    return mode


def _bounded_int(value: object, fallback: int, low: int, high: int, label: str) -> int:
    number = int(fallback if value is None else value)
    if not low <= number <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return number


def _bounded_float(value: object, fallback: float, low: float, high: float, label: str) -> float:
    number = float(fallback if value is None else value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{label} must be between {low:g} and {high:g}")
    return round(number, 2)


def _validated_bool(value: object, fallback: bool, label: str) -> bool:
    value = fallback if value is None else value
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false")
    return value


def _enum_value(value: object, fallback: str, allowed: tuple[str, ...], label: str) -> str:
    selected = str(fallback if value is None else value).strip().lower()
    if selected not in allowed:
        raise ValueError(f"{label} must be one of {', '.join(allowed)}")
    return selected


def validate_hostname(value: object) -> str:
    hostname = str(value or "").strip()
    if not hostname or len(hostname) > 100:
        raise ValueError("Hostname must be between 1 and 100 characters")
    if any(char in hostname for char in ('"', ';', '\\', "\0", "\n", "\r")):
        raise ValueError("Hostname contains a reserved command character")
    if not hostname.isprintable():
        raise ValueError("Hostname contains a non-printable character")
    return hostname


def validate_mode_settings(mode: str, settings: dict) -> dict:
    defaults = DEFAULT_MODE_SETTINGS[mode]
    formats = MODE_FORMATS[mode]
    key = str(settings.get("format", defaults["format"]))
    if key not in formats:
        raise ValueError(f"Match format must be one of {', '.join(formats)}")
    match_format = formats[key]

    pool = normalize_map_pool(settings.get("map_pool"), defaults["map_pool"])
    round_time = _bounded_float(
        settings.get("round_time"), defaults["round_time"], 0.5, 60, "Round time"
    )
    start_money = _bounded_int(
        settings.get("start_money"), defaults["start_money"], 0, 65535, "Start money"
    )
    max_money = _bounded_int(
        settings.get("max_money"), defaults["max_money"], 0, 65535, "Max money"
    )
    if max_money < start_money:
        raise ValueError("Max money must be greater than or equal to start money")

    return {
        "format": key,
        "map_pool": pool,
        # Derived from the selections above so the runtime contract stays stable.
        "map": pool[0],
        "capacity": match_format["capacity"],
        "game_alias": match_format["game_alias"],
        "hostname": validate_hostname(settings.get("hostname", defaults["hostname"])),
        # These settings are intentionally fixed because the streamlined panel
        # no longer exposes their former advanced controls.
        "lan": False,
        "cheats": False,
        "allow_lobby_connect_only": False,
        "limit_teams": 0,
        "auto_team_balance": False,
        "spectators_max": defaults["spectators_max"],
        "max_rounds": _bounded_int(settings.get("max_rounds"), defaults["max_rounds"], 1, 120, "Max rounds"),
        "freezetime": _bounded_int(settings.get("freezetime"), defaults["freezetime"], 0, 60, "Freeze time"),
        "warmup_time": _bounded_int(settings.get("warmup_time"), defaults["warmup_time"], 0, 600, "Warmup time"),
        "round_time": round_time,
        "buy_time": _bounded_int(settings.get("buy_time"), defaults["buy_time"], 0, 600, "Buy time"),
        "c4_timer": _bounded_int(settings.get("c4_timer"), defaults["c4_timer"], 10, 90, "C4 timer"),
        "start_money": start_money,
        "max_money": max_money,
        "bot_quota": match_format["capacity"],
        "bot_quota_mode": "match",
        "bot_difficulty": 3,
        "bot_chatter": "normal",
        "bot_join_after_player": True,
        "friendly_fire": normalize_friendly_fire(settings.get("friendly_fire"), defaults["friendly_fire"]),
        "ff_bullet_reduction": defaults["ff_bullet_reduction"],
        "ff_grenade_reduction": defaults["ff_grenade_reduction"],
        "ff_other_reduction": defaults["ff_other_reduction"],
        "tk_punish": defaults["tk_punish"],
        "overtime": _validated_bool(settings.get("overtime"), defaults["overtime"], "Overtime"),
        "overtime_max_rounds": _bounded_int(
            settings.get("overtime_max_rounds"), defaults["overtime_max_rounds"], 2, 30, "Overtime rounds"
        ),
    }


def selected_format(mode: str, settings: dict) -> dict:
    formats = MODE_FORMATS[mode]
    return formats.get(settings.get("format"), formats[DEFAULT_MODE_SETTINGS[mode]["format"]])


def runtime_cfg_path(mode: str) -> Path:
    return mode_dir(mode) / "cfg" / MODE_DEFS[mode]["startup"]["runtime_cfg"]



def validate_server_password(value: object, *, allow_empty: bool = False) -> str:
    password = str(value or "")
    if not password and allow_empty:
        return ""
    if not password or len(password) > SERVER_PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password must be between 1 and {SERVER_PASSWORD_MAX_LENGTH} characters")
    if any(char in password for char in ('"', ';', '\\', "\0", "\n", "\r")):
        raise ValueError("Password contains a reserved command character")
    if not password.isprintable():
        raise ValueError("Password contains a non-printable character")
    return password


# "nades" keeps grenade friendly fire but zeroes bullet and other damage, which
# is how the stock competitive friendly-fire scaling convars are meant to be used.
def hot_convar_lines(settings: dict) -> list[str]:
    friendly_fire = normalize_friendly_fire(settings.get("friendly_fire"), "off")
    enabled = 0 if friendly_fire == "off" else 1
    bullets = 0.0 if friendly_fire == "nades" else float(settings.get("ff_bullet_reduction", 0.33))
    other = 0.0 if friendly_fire == "nades" else float(settings.get("ff_other_reduction", 0.4))
    grenades = float(settings.get("ff_grenade_reduction", 0.25))
    round_time = float(settings.get("round_time", 1.92))
    return [
        f'hostname "{validate_hostname(settings.get("hostname", "CS2 Server"))}"',
        f"sv_lan {1 if settings.get('lan') else 0}",
        f"sv_cheats {1 if settings.get('cheats') else 0}",
        f"sv_allow_lobby_connect_only {1 if settings.get('allow_lobby_connect_only') else 0}",
        f"sv_maxplayers {settings.get('capacity', 10)}",
        f"mp_limitteams {settings.get('limit_teams', 0)}",
        f"mp_autoteambalance {1 if settings.get('auto_team_balance') else 0}",
        f"mp_spectators_max {settings.get('spectators_max', 2)}",
        f"bot_quota {settings.get('bot_quota', settings.get('capacity', 10))}",
        f"bot_quota_mode {settings.get('bot_quota_mode', 'match')}",
        f"bot_difficulty {settings.get('bot_difficulty', 3)}",
        f"bot_chatter {settings.get('bot_chatter', 'normal')}",
        f"bot_join_after_player {1 if settings.get('bot_join_after_player', True) else 0}",
        f"mp_friendlyfire {enabled}",
        f"ff_damage_reduction_bullets {bullets:g}",
        f"ff_damage_reduction_grenade {grenades:g}",
        f"ff_damage_reduction_other {other:g}",
        f"mp_tkpunish {1 if settings.get('tk_punish') else 0}",
        f"mp_maxrounds {settings.get('max_rounds', 24)}",
        f"mp_freezetime {settings.get('freezetime', 15)}",
        f"mp_warmuptime {settings.get('warmup_time', 60)}",
        f"mp_roundtime {round_time:g}",
        f"mp_roundtime_defuse {round_time:g}",
        f"mp_roundtime_hostage {round_time:g}",
        f"mp_buytime {settings.get('buy_time', 20)}",
        f"mp_c4timer {settings.get('c4_timer', 40)}",
        f"mp_startmoney {settings.get('start_money', 800)}",
        f"mp_maxmoney {settings.get('max_money', 16000)}",
        f"mp_overtime_enable {1 if settings.get('overtime') else 0}",
        f"mp_overtime_maxrounds {settings.get('overtime_max_rounds', 6)}",
    ]


def generate_runtime_cfg(mode: str, settings: dict, password_line: str) -> str:
    match_format = selected_format(mode, settings)
    lines = [
        "// Generated by CS2 Manager. Do not edit.",
        f'echo "[CS2 Manager] Applying {mode} runtime settings"',
        f'echo "[CS2 Manager] Match format {match_format["key"]} ({match_format["game_alias"]})"',
        password_line,
        *hot_convar_lines(settings),
        *match_format["cfg"],
        *MODE_DEFS[mode]["extra_cfg"],
    ]
    return "\n".join(lines) + "\n"


def write_runtime_cfg(mode: str, settings: dict) -> None:
    secret = load_secrets()
    password = (
        validate_server_password(secret.get("server_password"))
        if secret.get("password_enabled") and secret.get("server_password")
        else ""
    )
    password_line = f'sv_password "{password}"'
    path = runtime_cfg_path(mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(generate_runtime_cfg(mode, settings, password_line), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _set_json_path(document: dict, path: str, value) -> bool:
    """Set a dotted path inside an already-existing plugin config object."""
    node = document
    parts = path.split(".")
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            raise ValueError(f"Plugin config has no object at {path!r}")
        node = child
    leaf = parts[-1]
    if leaf not in node:
        raise ValueError(f"Plugin config has no key at {path!r}")
    if node[leaf] == value:
        return False
    node[leaf] = value
    return True


def apply_format_plugin_config(mode: str, settings: dict) -> str | None:
    """Write the selected format's values into the mode's plugin config file.

    Returns the config name when the file changed, so callers can decide whether
    a live sync is worthwhile.
    """
    target = selected_format(mode, settings)["plugin_config"]
    if not target:
        return None
    path = mode_config_path(mode, target["config"])
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{target['config']} is not a JSON object")
    changed = False
    for json_path, value in target["set"].items():
        changed = _set_json_path(document, json_path, value) or changed
    if not changed:
        return None
    _backup_and_write(path, document)
    return target["config"]


def write_active_mode_state(mode: str, settings: dict) -> None:
    write_json(
        ACTIVE_MODE_JSON,
        {"version": 1, "mode": mode, "settings": settings, "updated_at": now_iso()},
    )


def selected_runtime_mode() -> str | None:
    state = read_json(ACTIVE_MODE_JSON, {})
    mode = state.get("mode") if isinstance(state, dict) else None
    if mode in MODES:
        return mode
    last = load_server().get("last_mode")
    return last if last in MODES else None


# ---------------------------------------------------------------------------
# RCON
# ---------------------------------------------------------------------------
class SourceRcon:
    SERVERDATA_RESPONSE_VALUE = 0
    SERVERDATA_EXECCOMMAND = 2
    SERVERDATA_AUTH_RESPONSE = 2
    SERVERDATA_AUTH = 3

    def __init__(self, host, port, password, timeout=3.0):
        self.host, self.port, self.password, self.timeout = host, port, password, timeout
        self.sock = None
        self.request_id = int(time.time()) & 0x7FFFFFFF

    def __enter__(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._authenticate()
        return self

    def __exit__(self, *_):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _recv_exact(self, length):
        chunks, remaining = [], length
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise ConnectionError("RCON connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _send_packet(self, packet_type, body):
        self.request_id = (self.request_id + 1) & 0x7FFFFFFF
        payload = struct.pack("<ii", self.request_id, packet_type) + body.encode() + b"\0\0"
        self.sock.sendall(struct.pack("<i", len(payload)) + payload)
        return self.request_id

    def _recv_packet(self):
        size = struct.unpack("<i", self._recv_exact(4))[0]
        if size < 10 or size > 4 * 1024 * 1024:
            raise ValueError("Invalid RCON packet size")
        payload = self._recv_exact(size)
        request_id, packet_type = struct.unpack("<ii", payload[:8])
        return request_id, packet_type, payload[8:-2].decode("utf-8", errors="replace")

    def _authenticate(self):
        expected = self._send_packet(self.SERVERDATA_AUTH, self.password)
        for _ in range(4):
            response_id, packet_type, _ = self._recv_packet()
            if packet_type == self.SERVERDATA_AUTH_RESPONSE:
                if response_id == -1:
                    raise PermissionError("RCON authentication failed")
                if response_id == expected:
                    return
        raise PermissionError("RCON authentication response was not received")

    def command(self, command):
        expected = self._send_packet(self.SERVERDATA_EXECCOMMAND, command)
        for _ in range(6):
            response_id, packet_type, body = self._recv_packet()
            if response_id == expected and packet_type == self.SERVERDATA_RESPONSE_VALUE:
                return body
        return ""


def rcon_command(container: str, command: str, timeout: float = 5.0) -> str:
    with SourceRcon(container, RCON_PORT, RCON_PASSWORD, timeout=timeout) as rcon:
        return rcon.command(command)


def rcon_reachable(container: str) -> bool:
    if not RCON_PASSWORD:
        return False
    try:
        rcon_command(container, "echo cs2mgr_ping", timeout=2.5)
        return True
    except (OSError, RuntimeError, ValueError, PermissionError):
        return False


def next_rcon_generation() -> int:
    global RCON_JOB_GENERATION
    with RCON_JOB_LOCK:
        RCON_JOB_GENERATION += 1
        return RCON_JOB_GENERATION


def cancel_pending_rcon() -> None:
    next_rcon_generation()


def queue_runtime_ready(mode: str, rollback: tuple[str, dict] | None = None) -> None:
    if not RCON_PASSWORD:
        return
    generation = next_rcon_generation()

    def worker():
        deadline = time.monotonic() + RCON_APPLY_TIMEOUT
        while time.monotonic() < deadline:
            with RCON_JOB_LOCK:
                if generation != RCON_JOB_GENERATION:
                    return
            if rcon_reachable(GAME_CONTAINER):
                STATE_TIMESTAMPS["last_successful_start"] = now_iso()
                app.logger.info("%s is ready in %s", mode, GAME_CONTAINER)
                return
            time.sleep(2)

        app.logger.error("RCON readiness timed out for %s", mode)
        if rollback is None:
            return
        previous_mode, previous_settings = rollback
        with RCON_JOB_LOCK:
            if generation != RCON_JOB_GENERATION:
                return
        try:
            write_runtime_cfg(previous_mode, previous_settings)
            write_active_mode_state(previous_mode, previous_settings)
            server = load_server()
            server["last_mode"] = previous_mode
            save_server(server)
            with OPERATION_LOCK:
                client.containers.get(GAME_CONTAINER).restart(timeout=20)
            app.logger.error(
                "Rolled back failed mode %s to %s and restarted %s",
                mode,
                previous_mode,
                GAME_CONTAINER,
            )
            audit("mode.rollback", "started", f"failed={mode} restored={previous_mode}", target=previous_mode)
            queue_runtime_ready(previous_mode)
        except (DockerException, OSError, ValueError) as exc:
            app.logger.exception("Automatic mode rollback failed: %s", exc)

    threading.Thread(target=worker, daemon=True, name=f"ready-{mode}").start()


# ---------------------------------------------------------------------------
# Docker and status helpers
# ---------------------------------------------------------------------------
def container_state(name: str = GAME_CONTAINER) -> dict:
    mode = selected_runtime_mode()
    try:
        container = client.containers.get(name)
        container.reload()
        return {
            "name": name,
            "mode": mode,
            "label": MODES[mode]["label"] if mode else "CS2 Game",
            "status": container.status,
            "running": container.status == "running",
            "started_at": container.attrs.get("State", {}).get("StartedAt"),
            "restart_count": container.attrs.get("RestartCount", 0),
        }
    except NotFound:
        return {
            "name": name,
            "mode": mode,
            "label": MODES[mode]["label"] if mode else "CS2 Game",
            "status": "not-created",
            "running": False,
            "started_at": None,
            "restart_count": 0,
        }


def all_game_states() -> list[dict]:
    return [container_state()]


def active_container() -> dict | None:
    state = container_state()
    return state if state["running"] else None


def stop_game() -> None:
    try:
        container = client.containers.get(GAME_CONTAINER)
        container.reload()
        if container.status == "running":
            container.stop(timeout=20)
    except NotFound:
        return


def container_stats(name: str) -> dict:
    try:
        container = client.containers.get(name)
        container.reload()
        if container.status != "running":
            return {}
        stats = container.stats(stream=False)
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"].get("system_cpu_usage", 0) - stats["precpu_stats"].get("system_cpu_usage", 0)
        cpus = stats["cpu_stats"].get("online_cpus") or 1
        used = stats["memory_stats"].get("usage", 0)
        limit = stats["memory_stats"].get("limit", 0)
        return {
            "cpu_percent": round((cpu_delta / system_delta) * cpus * 100, 1) if system_delta else 0,
            "mem_used_mb": round(used / 1048576, 1),
            "mem_limit_mb": round(limit / 1048576, 1),
            "mem_percent": round((used / limit) * 100, 1) if limit else 0,
        }
    except (DockerException, KeyError, TypeError, ZeroDivisionError):
        return {}


def operational_state(active: dict | None) -> str:
    if active is None:
        return "Stopped"
    return "Ready" if rcon_reachable(active["name"]) else "StartingGame"


STATUS_COUNTS_RE = re.compile(r"players\s*:\s*(?P<humans>\d+)\s+humans,\s*(?P<bots>\d+)\s+bots\s*\((?P<max>\d+)\s*max", re.I)
STATUS_MAP_RE = re.compile(r"\[\s*1:\s*(?P<map>[A-Za-z0-9_]+)\s*\|")
PANEL_PLAYER_RE = re.compile(r"^PP\|(-?\d+)\|(\d+)\|(-?\d+)\|(\d+)\|([01])\|(.*)$")
TEAM_LABELS = {0: "None", 1: "Spectator", 2: "T", 3: "CT"}


def parse_current_map(text: str) -> str | None:
    match = STATUS_MAP_RE.search(text)
    return match.group("map") if match else None


def parse_player_counts(text: str) -> dict:
    match = STATUS_COUNTS_RE.search(text)
    return {key: int(value) for key, value in match.groupdict().items()} if match else {}


def parse_panel_players(text: str) -> list[dict] | None:
    if "PANELPLAYERS_BEGIN" not in text:
        return None
    rows = []
    for raw in text.splitlines():
        match = PANEL_PLAYER_RE.match(raw.strip())
        if not match:
            continue
        userid, steam64, team, ping, isbot, name = match.groups()
        rows.append({
            "userid": int(userid),
            "steamid64": steam64 if int(steam64) else None,
            "team": int(team),
            "team_label": TEAM_LABELS.get(int(team), "?"),
            "ping": int(ping),
            "bot": isbot == "1",
            "name": name,
        })
    return rows


def parse_players(text: str) -> list[dict]:
    rows = []
    in_players = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if "players---" in line or line.strip().startswith("id "):
            in_players = True
            continue
        if line.strip() == "#end":
            break
        if not in_players:
            continue
        id_match = re.match(r"\s*(\d+)\s", line)
        name_match = re.search(r"'([^']*)'\s*$", line)
        if not id_match or not name_match:
            continue
        tokens = line[: name_match.start()].split()
        rows.append({
            "userid": int(id_match.group(1)),
            "name": name_match.group(1),
            "steamid64": None,
            "team": 0,
            "team_label": "—",
            "ping": int(tokens[2]) if len(tokens) >= 3 and tokens[2].isdigit() else None,
            "bot": "BOT" in line,
        })
    return rows


UNKNOWN_COMMAND_RE = re.compile(r"unknown command", re.I)


def command_unknown(output: str) -> bool:
    return bool(UNKNOWN_COMMAND_RE.search(output or ""))


def gameinfo_has_metamod() -> bool | None:
    try:
        return "csgo/addons/metamod" in (SERVER_DIR / "game/csgo/gameinfo.gi").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def manager_versions() -> dict:
    return read_json(VERSIONS_JSON, {})


def verify_mounts() -> dict:
    checks: dict[str, bool | None] = {"modes:definitions": bool(MODE_DEFS) and not MODE_DEF_ERRORS}
    versions = manager_versions()
    installed_marker = SERVER_DIR / "game/csgo/addons/.cs2-manager-versions.json"
    installed_versions = read_json(installed_marker, {})
    checks["versions:file"] = VERSIONS_JSON.is_file()
    checks["versions:installed-marker"] = installed_marker.is_file()
    for mode, definition in MODE_DEFS.items():
        root = mode_dir(mode)
        for key in ("mode_cfg", "runtime_cfg"):
            name = definition["startup"][key]
            checks[f"{mode}:{name}"] = (root / "cfg" / name).is_file()
        for component, expected in definition["requires"].items():
            actual = versions.get(component, {}).get("version") if isinstance(versions.get(component), dict) else None
            checks[f"{mode}:requires:{component}"] = actual == expected
            checks[f"{mode}:installed:{component}"] = installed_versions.get(component) == expected
        for row in mode_defs.declared_mounts(definition):
            source = mode_defs.mount_source_path(row, root, SHARED_DIR)
            checks[f"{mode}:{row['owner']}:{row['target']}"] = source.is_file() if row["kind"] == "file" else source.is_dir()
        for plugin in definition["plugins"]:
            if plugin["build"]:
                source = mode_defs.build_project_path(plugin["build"], root, SHARED_DIR)
                checks[f"{mode}:{plugin['name']}:src"] = source.is_dir()
    checks["server:gameinfo"] = (SERVER_DIR / "game/csgo/gameinfo.gi").is_file()
    checks["server:cs2_binary"] = (SERVER_DIR / "game/bin/linuxsteamrt64/cs2").is_file()
    checks["gameinfo_metamod_line"] = gameinfo_has_metamod()
    checks["data:active-mode"] = ACTIVE_MODE_JSON.is_file() or load_server().get("last_mode") is None
    return checks


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def _start_mode(mode: str, restart_if_running: bool) -> dict:
    settings = validate_mode_settings(mode, load_mode(mode))
    save_mode(mode, settings)
    write_runtime_cfg(mode, settings)
    try:
        apply_format_plugin_config(mode, settings)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Match format could not be written to the plugin config: {exc}") from exc

    previous_mode = selected_runtime_mode()
    previous_settings = None
    if previous_mode in MODES and previous_mode != mode:
        previous_settings = validate_mode_settings(previous_mode, load_mode(previous_mode))
    previous_state = read_json(ACTIVE_MODE_JSON, {})
    previous_server = load_server()

    with OPERATION_LOCK:
        container = client.containers.get(GAME_CONTAINER)
        container.reload()
        write_active_mode_state(mode, settings)
        next_server = dict(previous_server)
        next_server["last_mode"] = mode
        save_server(next_server)
        try:
            if container.status == "running":
                if restart_if_running or previous_mode != mode:
                    cancel_pending_rcon()
                    container.restart(timeout=20)
            else:
                container.start()
        except DockerException:
            if previous_state:
                write_json(ACTIVE_MODE_JSON, previous_state)
            else:
                ACTIVE_MODE_JSON.unlink(missing_ok=True)
            save_server(previous_server)
            raise

    rollback = (
        (previous_mode, previous_settings)
        if previous_mode in MODES and previous_settings is not None and previous_mode != mode
        else None
    )
    queue_runtime_ready(mode, rollback=rollback)
    return settings


# ---------------------------------------------------------------------------
# Background jobs and maintenance helpers
# ---------------------------------------------------------------------------
JOBS: dict[str, "Job"] = {}
JOBS_LOCK = threading.Lock()
JOB_MAX = 50


class Job:
    def __init__(self, kind: str, user: str):
        self.id = uuid.uuid4().hex[:12]
        self.type = kind
        self.status = "Queued"
        self.step = None
        self.percent = 0
        self.start = now_iso()
        self.end = None
        self.user = user
        self.result = None
        self.error = None
        self.rollback_status = None
        self.log: list[str] = []
        self._lock = threading.Lock()

    def emit(self, text: str) -> None:
        with self._lock:
            self.log.append(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  {redact(text)}")
            self.log = self.log[-2000:]
        app.logger.info("[job %s] %s", self.id, text)

    def set(self, *, step=None, percent=None, status=None) -> None:
        with self._lock:
            if step is not None:
                self.step = step
                self.log.append(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  == {step} ==")
            if percent is not None:
                self.percent = percent
            if status is not None:
                self.status = status

    def to_dict(self, include_log=False) -> dict:
        value = {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "step": self.step,
            "percent": self.percent,
            "start": self.start,
            "end": self.end,
            "user": self.user,
            "result": self.result,
            "error": self.error,
            "rollback_status": self.rollback_status,
        }
        if include_log:
            value["log"] = list(self.log)
        return value


def start_job(kind: str, worker) -> Job:
    job = Job(kind, current_user() if has_request_context() else "system")
    with JOBS_LOCK:
        JOBS[job.id] = job
        finished = [item for item in JOBS.values() if item.status in ("Succeeded", "Failed", "Cancelled")]
        for stale in sorted(finished, key=lambda item: item.start)[: max(0, len(JOBS) - JOB_MAX)]:
            JOBS.pop(stale.id, None)

    def run():
        job.set(status="Running")
        try:
            worker(job)
            if job.status == "Running":
                job.set(status="Succeeded", percent=100)
        except Exception as exc:  # background boundary
            job.set(status="Failed")
            job.error = str(exc)
            job.emit(f"FAILED: {exc}")
        job.end = now_iso()
        audit(f"job.{kind}", job.status.lower(), f"job={job.id}", job_id=job.id)

    threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
    return job


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def make_backup(job: Job, scope: str = "config") -> Path:
    destination = BACKUPS_DIR / f"{scope}-{timestamp_slug()}"
    destination.mkdir(parents=True, exist_ok=True)
    for relative in ("compose.yml", ".env", ".env.example"):
        source = PROJECT_DIR / relative
        if source.exists():
            shutil.copy2(source, destination / Path(relative).name)
    for relative in ("panel", "modes", "data", "runtime", "updater", "shared"):
        source = PROJECT_DIR / relative
        if source.is_dir():
            shutil.copytree(source, destination / relative, ignore=shutil.ignore_patterns("*.tmp", "__pycache__", "bin", "obj"), dirs_exist_ok=True)
    STATE_TIMESTAMPS["last_backup"] = now_iso()
    job.emit(f"Backup -> {destination.name}")
    return destination


def run_updater_container(job: Job, updater_mode: str) -> int:
    if not CS2_DATA_PATH_HOST:
        raise RuntimeError("CS2_DATA_PATH is not configured for the panel")
    name = f"cs2-updater-job-{job.id}"
    try:
        client.containers.get(name).remove(force=True)
    except NotFound:
        pass
    container = client.containers.run(
        UPDATER_IMAGE,
        detach=True,
        name=name,
        environment={"CS2_UPDATER_MODE": updater_mode, "CS2_UPDATER_CONFIRM": UPDATER_CONFIRM_PHRASE},
        volumes={CS2_DATA_PATH_HOST: {"bind": "/home/steam/cs2-dedicated", "mode": "rw"}},
    )
    try:
        for chunk in container.logs(stream=True, follow=True):
            job.emit(chunk.decode("utf-8", errors="replace").rstrip())
        return container.wait().get("StatusCode", -1)
    finally:
        try:
            container.remove(force=True)
        except DockerException:
            pass


def restart_previous_mode(job: Job, mode: str) -> bool:
    try:
        _start_mode(mode, restart_if_running=True)
    except (ValueError, RuntimeError, DockerException, NotFound) as exc:
        job.emit(f"Restart failed: {exc}")
        return False
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if rcon_reachable(GAME_CONTAINER):
            return True
        time.sleep(3)
    return False


def _mode_to_restore() -> str | None:
    active = active_container()
    if active:
        return active["mode"]
    return selected_runtime_mode()


# ---------------------------------------------------------------------------
# Routes: status and lifecycle
# ---------------------------------------------------------------------------
@app.get("/")
@require_auth
def index():
    return render_template("index.html")


@app.get("/api/v3/status")
@require_auth
def api_status():
    try:
        states = all_game_states()
        active = states[0] if states[0]["running"] else None
        server = load_server()
        secret = load_secrets()
        return jsonify({
            "ok": True,
            "operational_state": operational_state(active),
            "containers": states,
            "active": active,
            "server": server,
            "password": {
                "enabled": bool(secret.get("password_enabled")),
                "has_password": bool(secret.get("server_password")),
                "policy": server.get("password_policy", "global"),
            },
            "visibility": "private" if secret.get("password_enabled") else "public",
            "modes": {mode: load_mode(mode) for mode in MODES},
            "mode_order": MODE_ORDER,
            "mode_defaults": DEFAULT_MODE_SETTINGS,
            "mode_meta": {
                mode: {
                    "label": meta["label"],
                    "implementation": meta["implementation"],
                    "container": GAME_CONTAINER,
                    "server_config": meta["server_config"],
                    "capacity": CAPACITY_RANGES[mode],
                    "formats": [
                        {key: entry[key] for key in mode_defs.FORMAT_PUBLIC_FIELDS}
                        for entry in MODE_DEFS[mode]["formats"]
                    ],
                    "requires": meta["requires"],
                    "plugins": [{"name": p["name"], "role": p["role"], "required": p["required"]} for p in MODE_DEFS[mode]["plugins"]],
                    "actions": [{key: action[key] for key in mode_defs.ACTION_PUBLIC_FIELDS} for action in MODE_ACTIONS.get(mode, [])],
                }
                for mode, meta in MODES.items()
            },
            "mode_definition_errors": MODE_DEF_ERRORS,
            "apply_levels": APPLY_LEVELS,
            "friendly_fire_modes": list(mode_defs.FRIENDLY_FIRE_MODES),
            "allowed_maps": ALLOWED_MAPS,
            "rcon_available": bool(RCON_PASSWORD),
            "timestamps": STATE_TIMESTAMPS,
            "endpoint": {"ip": "127.0.0.1", "port": RCON_PORT},
        })
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/v3/health")
@require_auth
def api_health():
    active = active_container()
    checks = {
        "single_active_service": True,
        "rcon": False,
        "metamod": None,
        "counterstrikesharp": None,
        "required_plugins": {},
        "map": None,
        "players": None,
    }
    stats = {}
    if active:
        checks["rcon"] = rcon_reachable(GAME_CONTAINER)
        stats = container_stats(GAME_CONTAINER)
        if checks["rcon"]:
            try:
                meta = rcon_command(GAME_CONTAINER, "meta list", 4)
                css = rcon_command(GAME_CONTAINER, "css_plugins list", 4)
                checks["metamod"] = not command_unknown(meta) and bool(re.search(r"listing\s+\d+\s+plugin|CounterStrikeSharp", meta, re.I))
                checks["counterstrikesharp"] = not command_unknown(css) and bool(re.search(r"\[#\d+:|plugins?\s+loaded|loaded by CounterStrikeSharp", css, re.I))
                combined = (meta + "\n" + css).lower()
                for plugin in MODE_DEFS[active["mode"]]["required_plugins"]:
                    checks["required_plugins"][plugin] = any(alias in combined for alias in MODE_DEFS[active["mode"]]["plugin_aliases"][plugin])
                status = rcon_command(GAME_CONTAINER, "status", 4)
                checks["map"] = parse_current_map(status)
                checks["players"] = parse_player_counts(status).get("humans")
            except (OSError, RuntimeError, ValueError, PermissionError) as exc:
                checks["rcon_error"] = str(exc)
    return jsonify({"ok": True, "active_mode": active["mode"] if active else None, "checks": checks, "stats": stats})


@app.get("/api/v3/metrics")
@require_auth
def api_metrics():
    active = active_container()
    return jsonify({"ok": True, "stats": container_stats(GAME_CONTAINER) if active else {}})


@app.post("/api/v3/server/start")
@require_auth
def api_server_start():
    mode = (request.get_json(silent=True) or {}).get("mode") or load_server().get("last_mode")
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown or unset mode"}), 400
    try:
        settings = _start_mode(mode, restart_if_running=False)
        audit("server.start", "ok", f"mode={mode}", target=mode)
        return jsonify({"ok": True, "mode": mode, "settings": settings})
    except NotFound:
        return jsonify({"ok": False, "error": "Container not created. Run the setup/start script."}), 409
    except (ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/v3/server/stop")
@require_auth
def api_server_stop():
    try:
        cancel_pending_rcon()
        with OPERATION_LOCK:
            stop_game()
        audit("server.stop", "ok")
        return jsonify({"ok": True})
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/v3/server/restart")
@require_auth
def api_server_restart():
    active = active_container()
    if not active:
        return jsonify({"ok": False, "error": "No game mode is running"}), 409
    try:
        with OPERATION_LOCK:
            client.containers.get(GAME_CONTAINER).restart(timeout=20)
        queue_runtime_ready(active["mode"])
        audit("server.restart", "ok", target=active["mode"])
        return jsonify({"ok": True, "mode": active["mode"]})
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/v3/server/refresh")
@require_auth
def api_server_refresh():
    return jsonify({"ok": True})


@app.get("/api/v3/commands")
@require_auth
def api_commands():
    mode = selected_runtime_mode()
    settings = load_mode(mode) if mode in MODES else None
    return jsonify({"ok": True, "mode": mode, "groups": command_catalog(mode, settings)})


@app.post("/api/v3/server/map")
@require_auth
def api_server_map():
    active = active_container()
    if not active:
        return jsonify({"ok": False, "error": "No game mode is running"}), 409
    mode = active["mode"]
    try:
        target = normalize_map((request.get_json(silent=True) or {}).get("map"))
        pool = validate_mode_settings(mode, load_mode(mode))["map_pool"]
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if target not in pool:
        return jsonify({"ok": False, "error": "Map is not in the active map pool"}), 400
    try:
        output = rcon_command(GAME_CONTAINER, f"changelevel {target}")
        audit("server.map", "ok", f"map={target}", target=mode)
        return jsonify({"ok": True, "map": target, "output": redact(output)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


# ---------------------------------------------------------------------------
# Routes: modes
# ---------------------------------------------------------------------------
@app.get("/api/v3/modes")
@require_auth
def api_modes():
    return jsonify({"ok": True, "modes": {mode: load_mode(mode) for mode in MODES}, "order": MODE_ORDER, "meta": {mode: {"label": MODES[mode]["label"], "implementation": MODES[mode]["implementation"]} for mode in MODES}})


@app.get("/api/v3/modes/<mode>")
@require_auth
def api_mode_get(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    definition = MODE_DEFS[mode]
    return jsonify({
        "ok": True,
        "mode": mode,
        "settings": load_mode(mode),
        "meta": {
            "label": MODES[mode]["label"],
            "implementation": MODES[mode]["implementation"],
            "container": GAME_CONTAINER,
            "game_alias": definition["startup"]["game_alias"],
            "capacity": CAPACITY_RANGES[mode],
            "requires": definition["requires"],
            "plugins": [{"name": p["name"], "role": p["role"], "required": p["required"]} for p in definition["plugins"]],
        },
    })


@app.put("/api/v3/modes/<mode>/settings")
@require_auth
def api_mode_settings(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    value = load_mode(mode)
    value.update(request.get_json(silent=True) or {})
    try:
        value = validate_mode_settings(mode, value)
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    save_mode(mode, value)
    audit("mode.settings", "ok", mode, target=mode)
    return jsonify({"ok": True, "mode": mode, "settings": value})


@app.post("/api/v3/modes/<mode>/apply")
@require_auth
def api_mode_apply(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    try:
        settings = validate_mode_settings(mode, load_mode(mode))
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    save_mode(mode, settings)
    write_runtime_cfg(mode, settings)
    try:
        changed_config = apply_format_plugin_config(mode, settings)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if selected_runtime_mode() == mode:
        write_active_mode_state(mode, settings)
    active = active_container()
    applied_hot = False
    map_reloaded = False
    if active and active["mode"] == mode and rcon_reachable(GAME_CONTAINER):
        try:
            for line in hot_convar_lines(settings):
                rcon_command(GAME_CONTAINER, line)
            live_map = parse_current_map(rcon_command(GAME_CONTAINER, "status", 4))
            if live_map and live_map != settings["map"]:
                rcon_command(GAME_CONTAINER, f"changelevel {settings['map']}")
                map_reloaded = True
            applied_hot = True
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            app.logger.warning("hot apply failed: %s", exc)
    if changed_config and active and active["mode"] == mode:
        try:
            sync_live_config(mode, changed_config)
        except (DockerException, RuntimeError, OSError) as exc:
            app.logger.warning("format plugin config sync failed: %s", exc)
    STATE_TIMESTAMPS["last_config_apply"] = now_iso()
    audit("mode.apply", "ok", f"hot={applied_hot} map_reload={map_reloaded}", target=mode)
    return jsonify({
        "ok": True,
        "mode": mode,
        "applied_hot": applied_hot,
        "map_reloaded": map_reloaded,
        "plugin_config": changed_config,
        "note": "the match format applies on the next start or restart",
    })


@app.post("/api/v3/modes/<mode>/start")
@require_auth
def api_mode_start(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    payload = request.get_json(silent=True) or {}
    if payload:
        current = load_mode(mode)
        current.update(payload)
        try:
            save_mode(mode, validate_mode_settings(mode, current))
        except (ValueError, TypeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    try:
        settings = _start_mode(mode, restart_if_running=True)
        audit("mode.start", "ok", target=mode)
        return jsonify({"ok": True, "mode": mode, "settings": settings})
    except NotFound:
        return jsonify({"ok": False, "error": "Container not created"}), 409
    except (ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/v3/modes/switch")
@require_auth
def api_mode_switch():
    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 400
    try:
        settings = _start_mode(mode, restart_if_running=True)
        write_json(CONSOLE_HISTORY_JSON, {"items": []})
        audit("mode.switch", "ok", target=mode)
        return jsonify({"ok": True, "mode": mode, "settings": settings})
    except NotFound:
        return jsonify({"ok": False, "error": "Container not created"}), 409
    except (ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/v3/modes/<mode>/actions")
@require_auth
def api_mode_actions(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    return jsonify({"ok": True, "mode": mode, "actions": [{key: action[key] for key in mode_defs.ACTION_PUBLIC_FIELDS} for action in MODE_ACTIONS.get(mode, [])]})


@app.post("/api/v3/modes/<mode>/action")
@require_auth
def api_mode_action(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    key = (request.get_json(silent=True) or {}).get("action")
    action = next((item for item in MODE_ACTIONS.get(mode, []) if item["key"] == key), None)
    if not action:
        return jsonify({"ok": False, "error": "Unknown action for this mode"}), 400
    active = active_container()
    if not active or active["mode"] != mode:
        return jsonify({"ok": False, "error": f"{MODES[mode]['label']} is not the active mode"}), 409
    try:
        if mode == "heroshift" and key == "reload_skills":
            sync_live_config("heroshift", "heroshift.json")
        output = rcon_command(GAME_CONTAINER, action["cmd"], 6)
        audit("mode.action", "ok", f"{mode}:{key}", target=mode)
        return jsonify({"ok": True, "action": key, "command": action["cmd"], "output": redact(output)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/v3/modes/<mode>/preview")
@require_auth
def api_mode_preview(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    pending = request.get_json(silent=True) or {}
    saved = load_mode(mode)
    changes = []
    for field, new_value in pending.items():
        if saved.get(field) == new_value:
            continue
        level = APPLY_LEVELS.get(field, "hot")
        changes.append({"field": field, "old": saved.get(field), "new": new_value, "apply_level": level, "map_reload": level == "map_reload", "game_restart": level == "game_restart", "disconnects_players": level in ("map_reload", "game_restart")})
    highest = "game_restart" if any(c["apply_level"] == "game_restart" for c in changes) else "map_reload" if any(c["apply_level"] == "map_reload" for c in changes) else "hot"
    return jsonify({"ok": True, "mode": mode, "changes": changes, "highest_apply_level": highest})


# ---------------------------------------------------------------------------
# HeroShift config
# ---------------------------------------------------------------------------
HEROSHIFT_BUILT_IN_SKILL_COUNT = 146


def mode_config_path(mode: str, name: str) -> Path:
    definition = MODE_DEFS.get(mode)
    entry = next((item for item in definition["configs"] if item["name"] == name), None) if definition else None
    if entry is None:
        raise FileNotFoundError(f"{mode} does not declare config {name!r}")
    return mode_defs.mount_source_path(entry, mode_dir(mode), SHARED_DIR)


def read_hs_config() -> dict:
    return json.loads(
        mode_config_path("heroshift", "heroshift.json").read_text(encoding="utf-8")
    )


def _backup_and_write(path: Path, value) -> str | None:
    backup_name = None
    if path.exists():
        try:
            relative = path.resolve().relative_to(MODES_ROOT.resolve())
            mode_id = relative.parts[0]
        except (OSError, ValueError, IndexError):
            mode_id = "unknown"
        backup_dir = BACKUPS_DIR / "config" / mode_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{path.name}.bak-{timestamp_slug()}"
        shutil.copy2(path, backup)
        backup_name = backup.name
        for stale in sorted(backup_dir.glob(f"{path.name}.bak-*"))[:-10]:
            stale.unlink(missing_ok=True)
    write_json(path, value)
    return backup_name


def sync_live_config(mode: str, name: str) -> None:
    container = client.containers.get(GAME_CONTAINER)
    result = container.exec_run([
        "/usr/local/bin/mode-applier",
        "--modes-root", "/manager/modes",
        "--shared-root", "/manager/shared",
        "--server-root", "/home/steam/cs2-dedicated",
        "--inventory", "/home/steam/cs2-dedicated/.cs2-manager/managed-files.json",
        "--versions", "/manager/shared/frameworks/versions.json",
        "sync-config", mode, name,
    ])
    if result.exit_code != 0:
        raise RuntimeError(result.output.decode("utf-8", errors="replace"))


@app.get("/api/v3/modes/heroshift/diag")
@require_auth
def api_hero_diag():
    active = active_container()
    try:
        config = read_hs_config()
        overrides = config.get("skills") or {}
        if not isinstance(overrides, dict):
            raise ValueError("HeroShift skills overrides must be an object")
        disabled = sum(
            1
            for value in overrides.values()
            if isinstance(value, dict) and value.get("enabled") is False
        )
        counts = {
            "active_count": HEROSHIFT_BUILT_IN_SKILL_COUNT - disabled,
            "total": HEROSHIFT_BUILT_IN_SKILL_COUNT,
            "configured_overrides": len(overrides),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        counts = {"active_count": None, "total": None, "configured_overrides": None}
    if not active or active["mode"] != "heroshift":
        return jsonify({"ok": True, "loaded": False, "active": False, "diag": counts, "note": "HeroShift is not active"})
    try:
        combined = (rcon_command(GAME_CONTAINER, "css_plugins list", 5) + "\n" + rcon_command(GAME_CONTAINER, "meta list", 5)).lower()
        counts["raytrace"] = "raytrace" in combined
        return jsonify({"ok": True, "loaded": "heroshift" in combined, "active": True, "diag": counts})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


# ---------------------------------------------------------------------------
# Console, players, password and logs
# ---------------------------------------------------------------------------
BLOCKED_COMMANDS = {"quit", "exit", "_restart", "crash"}
DANGEROUS_PREFIXES = ("sv_password", "rcon_password", "sv_cheats")
DISRUPTIVE_PREFIXES = ("mp_restartgame", "changelevel", "map", "kickid", "kick", "css_endmatch", "css_restart")


def classify_command(command: str) -> str:
    head = command.strip().split()[0].lower() if command.strip() else ""
    if head in BLOCKED_COMMANDS:
        return "Blocked"
    if any(command.lower().startswith(prefix) for prefix in DANGEROUS_PREFIXES):
        return "Dangerous"
    if any(head == prefix or command.lower().startswith(prefix) for prefix in DISRUPTIVE_PREFIXES):
        return "Disruptive"
    if head in ("status", "users", "meta", "css_plugins", "version", "stats"):
        return "ReadOnly"
    return "Normal"



def validate_console_command(value: object) -> str:
    command = str(value or "").strip()
    if (
        not command
        or len(command) > CONSOLE_COMMAND_MAX_LENGTH
        or any(char in command for char in ("\0", "\n", "\r", ";"))
    ):
        raise ValueError("Invalid command")
    return command


def catalog_allows_command(mode: str, settings: dict, command: str) -> bool:
    normalized = command.strip().lower()
    for group in command_catalog(mode, settings):
        for entry in group["commands"]:
            base = entry["cmd"].strip().lower()
            if entry.get("arg_hint"):
                if normalized.startswith(base + " "):
                    return True
            elif normalized == base:
                return True
    return False


@app.post("/api/v3/console/command")
@require_auth
def api_console():
    try:
        command = validate_console_command((request.get_json(silent=True) or {}).get("command", ""))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    risk = classify_command(command)
    if risk == "Blocked":
        return jsonify({"ok": False, "error": f"Command {command!r} is blocked", "risk": risk}), 403
    active = active_container()
    if not active:
        return jsonify({"ok": False, "error": "No game mode is running"}), 409
    try:
        settings = validate_mode_settings(active["mode"], load_mode(active["mode"]))
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc), "risk": risk}), 400
    if not catalog_allows_command(active["mode"], settings, command):
        return jsonify({
            "ok": False,
            "error": "Command is not in the approved catalog for the active mode",
            "risk": risk,
        }), 403
    try:
        output = rcon_command(GAME_CONTAINER, command)
        history = read_json(CONSOLE_HISTORY_JSON, {"items": []}).get("items", [])
        history.append({"time": now_iso(), "command": redact(command), "risk": risk})
        write_json(CONSOLE_HISTORY_JSON, {"items": history[-200:]})
        audit("console.command", "ok", command, target=active["mode"])
        return jsonify({"ok": True, "container": GAME_CONTAINER, "command": command, "risk": risk, "output": redact(output)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc), "risk": risk}), 502


@app.get("/api/v3/console/history")
@require_auth
def api_console_history():
    return jsonify({"ok": True, "items": read_json(CONSOLE_HISTORY_JSON, {"items": []}).get("items", [])})


@app.get("/api/v3/players")
@require_auth
def api_players():
    active = active_container()
    if not active:
        return jsonify({"ok": True, "players": [], "active": None})
    if not rcon_reachable(GAME_CONTAINER):
        return jsonify({"ok": True, "players": [], "active": active["mode"], "note": "RCON not reachable yet"})
    try:
        players = parse_panel_players(rcon_command(GAME_CONTAINER, "css_panel_players"))
        source = "plugin"
        if players is None:
            source = "status"
            players = parse_players(rcon_command(GAME_CONTAINER, "status"))
        return jsonify({"ok": True, "players": players, "active": active["mode"], "source": source})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


def _player_rcon(action: str, ident: str, command: str):
    if not active_container():
        return jsonify({"ok": False, "error": "No game mode is running"}), 409
    try:
        output = rcon_command(GAME_CONTAINER, command)
        audit(f"player.{action}", "ok", command, target=ident)
        return jsonify({"ok": True, "output": redact(output)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/v3/players/<ident>/kick")
@require_auth
def api_player_kick(ident):
    userid = (request.get_json(silent=True) or {}).get("userid")
    if userid is None:
        return jsonify({"ok": False, "error": "userid is required"}), 400
    return _player_rcon("kick", ident, f"kickid {int(userid)}")


@app.post("/api/v3/players/<ident>/ban")
@require_auth
def api_player_ban(ident):
    body = request.get_json(silent=True) or {}
    userid = body.get("userid")
    if userid is None:
        return jsonify({"ok": False, "error": "userid is required"}), 400
    minutes = max(0, int(body.get("minutes", 0)))
    try:
        output = rcon_command(GAME_CONTAINER, f"banid {minutes} {int(userid)}")
        if minutes == 0:
            output += "\n" + rcon_command(GAME_CONTAINER, "writeid")
        rcon_command(GAME_CONTAINER, f"kickid {int(userid)}")
        return jsonify({"ok": True, "output": redact(output)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/v3/players/<steamid64>/team")
@require_auth
def api_player_team(steamid64):
    return jsonify({"ok": False, "error": "Team move requires a plugin"}), 501


@app.get("/api/v3/server/password-policy")
@require_auth
def api_password_get():
    secret = load_secrets()
    return jsonify({"ok": True, "enabled": bool(secret.get("password_enabled")), "has_password": bool(secret.get("server_password")), "policy": load_server().get("password_policy", "global")})


def _apply_password_live(secret: dict) -> None:
    value = (
        validate_server_password(secret.get("server_password"))
        if secret.get("password_enabled")
        else ""
    )
    active = active_container()
    if active and rcon_reachable(GAME_CONTAINER):
        try:
            rcon_command(GAME_CONTAINER, f'sv_password "{value}"')
        except (OSError, RuntimeError, ValueError, PermissionError):
            pass
    mode = selected_runtime_mode()
    if mode:
        write_runtime_cfg(mode, load_mode(mode))


@app.put("/api/v3/server/password-policy")
@require_auth
def api_password_set():
    payload = request.get_json(silent=True) or {}
    secret = load_secrets()
    action = payload.get("action", "set")
    try:
        if action == "generate":
            secret["server_password"] = validate_server_password(secrets_mod.token_urlsafe(9))
            secret["password_enabled"] = True
        elif action == "enable":
            if payload.get("password") is not None:
                secret["server_password"] = validate_server_password(payload["password"])
            elif not secret.get("server_password"):
                return jsonify({"ok": False, "error": "No password set to enable"}), 400
            else:
                secret["server_password"] = validate_server_password(secret["server_password"])
            secret["password_enabled"] = True
        elif action == "set" and payload.get("password") is not None:
            secret["server_password"] = validate_server_password(payload["password"])
            secret["password_enabled"] = True
        else:
            return jsonify({"ok": False, "error": "Unknown action or missing password"}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    save_secrets(secret)
    _apply_password_live(secret)
    return jsonify({"ok": True, "enabled": True, "has_password": True})


@app.post("/api/v3/server/password/disable")
@require_auth
def api_password_disable():
    secret = load_secrets()
    secret["password_enabled"] = False
    save_secrets(secret)
    _apply_password_live(secret)
    return jsonify({"ok": True, "enabled": False})


@app.get("/api/v3/server/visibility")
@require_auth
def api_visibility_get():
    secret = load_secrets()
    return jsonify({
        "ok": True,
        "visibility": "private" if secret.get("password_enabled") else "public",
        "has_password": bool(secret.get("server_password")),
    })


@app.put("/api/v3/server/visibility")
@require_auth
def api_visibility_set():
    payload = request.get_json(silent=True) or {}
    visibility = str(payload.get("visibility", "")).strip().lower()
    if visibility not in VISIBILITY_MODES:
        return jsonify({"ok": False, "error": "Visibility must be public or private"}), 400
    secret = load_secrets()
    if visibility == "public":
        secret["password_enabled"] = False
    else:
        try:
            if payload.get("password") is not None:
                secret["server_password"] = validate_server_password(payload["password"])
            elif secret.get("server_password"):
                secret["server_password"] = validate_server_password(secret["server_password"])
            else:
                return jsonify({
                    "ok": False,
                    "error": "Set a lobby password before switching to Private",
                }), 400
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        secret["password_enabled"] = True
    save_secrets(secret)
    server = load_server()
    server["access_mode"] = visibility
    save_server(server)
    _apply_password_live(secret)
    audit("server.visibility", "ok", f"visibility={visibility}")
    return jsonify({
        "ok": True,
        "visibility": visibility,
        "has_password": bool(secret.get("server_password")),
    })


LOG_SOURCES = {
    "game": {"label": "Game"},
    "docker": {"label": "Docker / container"},
    "panel": {"label": "Panel"},
    "updater": {"label": "SteamCMD / Updater"},
    "audit": {"label": "Audit"},
    "plugin": {"label": "Plugins (filtered)"},
}


@app.get("/api/v3/logs/sources")
@require_auth
def api_log_sources():
    sources = [{"id": key, "label": value["label"]} for key, value in LOG_SOURCES.items()]
    sources.append({"id": f"container:{GAME_CONTAINER}", "label": "CS2 game container"})
    return jsonify({"ok": True, "sources": sources})


@app.get("/api/v3/logs/stream")
@require_auth
def api_logs():
    source = request.args.get("source", "game").strip()
    try:
        tail = min(max(int(request.args.get("tail", LOG_TAIL_DEFAULT)), 20), 2000)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid tail"}), 400
    if source == "audit":
        path = AUDIT_DIR / f"audit-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return jsonify({"ok": True, "source": source, "logs": "\n".join(text.splitlines()[-tail:])})
    if source == "panel":
        container_name = PANEL_CONTAINER
    elif source == "updater":
        container_name = UPDATER_CONTAINER
    elif source.startswith("container:"):
        container_name = source.split(":", 1)[1]
        if container_name != GAME_CONTAINER:
            return jsonify({"ok": False, "error": "Unknown container"}), 400
    elif source in ("game", "docker", "plugin"):
        container_name = GAME_CONTAINER
    else:
        return jsonify({"ok": False, "error": "Unknown log source"}), 400
    try:
        container = client.containers.get(container_name)
        container.reload()
        output = redact(container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace"))
        if source == "plugin":
            keep = ("MatchZy", "Metamod", "CounterStrikeSharp", "AutoReady", "Retakes", "Instadefuse", "HeroShift", "RayTrace", "[CS2 Manager]")
            output = "\n".join(line for line in output.splitlines() if any(token in line for token in keep))
        return jsonify({"ok": True, "source": source, "container": container_name, "status": container.status, "logs": output})
    except NotFound:
        return jsonify({"ok": True, "source": source, "container": container_name, "status": "not-created", "logs": "Container not created yet."})
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Maintenance and panel lifecycle
# ---------------------------------------------------------------------------
@app.get("/api/v3/maintenance/jobs")
@require_auth
def api_jobs():
    return jsonify({"ok": True, "jobs": [job.to_dict() for job in sorted(JOBS.values(), key=lambda item: item.start, reverse=True)]})


@app.get("/api/v3/maintenance/jobs/<job_id>")
@app.get("/api/v3/panel/build-jobs/<job_id>")
@require_auth
def api_job_detail(job_id):
    job = JOBS.get(job_id)
    return jsonify({"ok": True, "job": job.to_dict(include_log=True)}) if job else (jsonify({"ok": False, "error": "Unknown job"}), 404)


@app.route("/api/v3/maintenance/verify-mounts", methods=["GET", "POST"])
@require_auth
def api_verify_mounts():
    checks = verify_mounts()
    return jsonify({"ok": True, "all_present": all(value is True for value in checks.values() if isinstance(value, bool)), "checks": checks})


@app.post("/api/v3/maintenance/backup")
@require_auth
def api_backup():
    def worker(job):
        job.result = {"path": make_backup(job, "manual").name}
    return jsonify({"ok": True, "job": start_job("backup", worker).to_dict()}), 202


@app.post("/api/v3/maintenance/repair-metamod")
@require_auth
def api_repair_metamod():
    restore = _mode_to_restore()

    def worker(job):
        make_backup(job, "pre-repair")
        with OPERATION_LOCK:
            stop_game()
        if run_updater_container(job, "repair-metamod") != 0:
            raise RuntimeError("Metamod repair failed")
        if restore and not restart_previous_mode(job, restore):
            raise RuntimeError("Post-repair restart failed")
        job.result = {"gameinfo_metamod": gameinfo_has_metamod()}

    return jsonify({"ok": True, "job": start_job("repair-metamod", worker).to_dict()}), 202


def _run_steamcmd_workflow(kind: str, updater_mode: str):
    if (request.get_json(silent=True) or {}).get("confirm") != UPDATER_CONFIRM_PHRASE:
        return jsonify({"ok": False, "error": f'Owner confirmation required: {UPDATER_CONFIRM_PHRASE}'}), 403
    restore = _mode_to_restore()

    def worker(job):
        make_backup(job, f"pre-{kind}")
        with OPERATION_LOCK:
            stop_game()
        if run_updater_container(job, updater_mode) != 0:
            raise RuntimeError(f"SteamCMD {updater_mode} failed")
        STATE_TIMESTAMPS["last_manual_update"] = now_iso()
        if restore and not restart_previous_mode(job, restore):
            raise RuntimeError("Post-update verification failed")
        job.result = {"mode": updater_mode, "restored": restore}

    return jsonify({"ok": True, "job": start_job(kind, worker).to_dict()}), 202


@app.post("/api/v3/maintenance/update")
@require_auth
def api_update():
    return _run_steamcmd_workflow("update", "update")


@app.post("/api/v3/maintenance/validate")
@require_auth
def api_validate():
    return _run_steamcmd_workflow("validate", "validate")


@app.post("/api/v3/maintenance/restore")
@require_auth
def api_restore():
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != UPDATER_CONFIRM_PHRASE:
        return jsonify({"ok": False, "error": "Owner confirmation required"}), 403
    name = str(body.get("backup", "")).strip()
    target = (BACKUPS_DIR / name).resolve()
    if not name or BACKUPS_DIR.resolve() not in target.parents or not target.is_dir():
        return jsonify({"ok": False, "error": "Unknown backup folder"}), 400

    def worker(job):
        with OPERATION_LOCK:
            stop_game()
        for relative in ("compose.yml", ".env", ".env.example"):
            source = target / relative
            if source.exists():
                shutil.copy2(source, PROJECT_DIR / relative)
        for relative in ("modes", "data", "shared", "runtime", "updater", "panel"):
            source = target / relative
            if source.is_dir():
                shutil.copytree(source, PROJECT_DIR / relative, dirs_exist_ok=True)
        job.result = {"restored_from": name}

    return jsonify({"ok": True, "job": start_job("restore", worker).to_dict()}), 202


@app.post("/api/v3/panel/restart")
@require_auth
def api_panel_restart():
    def restart():
        time.sleep(1)
        try:
            client.containers.get(PANEL_CONTAINER).restart(timeout=10)
        except DockerException:
            pass
    threading.Thread(target=restart, daemon=True).start()
    return jsonify({"ok": True, "note": "Panel restarting"})


@app.post("/api/v3/panel/rebuild")
@require_auth
def api_panel_rebuild():
    def worker(job):
        source = PROJECT_DIR / "panel"
        _, errors = mode_defs.load_definitions(MODES_ROOT)
        if errors:
            raise RuntimeError("Mode definitions are invalid: " + "; ".join(errors))
        candidate = "cs2-server-panel:candidate"
        _, logs = client.images.build(path=str(source), tag=candidate, rm=True, pull=False)
        for row in logs:
            if isinstance(row, dict) and row.get("stream"):
                job.emit(row["stream"].rstrip())
        test_name = f"panel-healthcheck-{job.id}"
        test = client.containers.run(candidate, command=["python", "-c", "import app; print('IMPORT_OK')"], detach=True, name=test_name, network_mode="none", environment={"PANEL_DATA_DIR": "/tmp/d", "PANEL_MODES_DIR": "/tmp/m"})
        output = test.logs(stream=False).decode("utf-8", errors="replace")
        code = test.wait().get("StatusCode", -1)
        test.remove(force=True)
        if code != 0 or "IMPORT_OK" not in output:
            raise RuntimeError("Candidate panel image failed health check")
        client.images.get(candidate).tag("cs2-server-panel", "latest")
        job.result = {"applied": _launch_panel_applier(job)}

    return jsonify({"ok": True, "job": start_job("panel-rebuild", worker).to_dict()}), 202


def _launch_panel_applier(job: Job) -> bool:
    if not MANAGER_PATH_HOST:
        return False
    try:
        client.containers.run(
            "docker:cli",
            command=["sh", "-c", f"sleep 2 && docker compose -p {COMPOSE_PROJECT} -f /work/compose.yml up -d panel"],
            detach=True,
            remove=True,
            name=f"panel-applier-{job.id}",
            working_dir="/work",
            volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}, MANAGER_PATH_HOST: {"bind": "/work", "mode": "rw"}},
        )
        return True
    except DockerException:
        return False


@app.get("/api/v3/audit")
@require_auth
def api_audit():
    path = AUDIT_DIR / f"audit-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    items = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return jsonify({"ok": True, "items": items})


def ensure_data_files() -> None:
    if not SERVER_JSON.exists():
        save_server(DEFAULT_SERVER)
    for mode in MODES:
        if not (MODES_DIR / f"{mode}.json").exists():
            save_mode(mode, DEFAULT_MODE_SETTINGS[mode])
    if not SECRETS_JSON.exists():
        password = os.environ.get("CS2_PASSWORD", "")
        save_secrets({"password_enabled": bool(password), "server_password": password, "per_mode": {}})
    for mode in MODES:
        try:
            settings = validate_mode_settings(mode, load_mode(mode))
            save_mode(mode, settings)
            write_runtime_cfg(mode, settings)
        except (OSError, ValueError, TypeError) as exc:
            app.logger.warning("runtime cfg seed failed for %s: %s", mode, exc)
    last = load_server().get("last_mode")
    if last in MODES and not ACTIVE_MODE_JSON.exists():
        try:
            settings = validate_mode_settings(last, load_mode(last))
            write_active_mode_state(last, settings)
        except (OSError, ValueError):
            pass


ensure_data_files()
