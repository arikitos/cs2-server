"""CS2 Manager Panel V3 — backend.

Single control plane for the CS2 server. Implements the Phase 1 surface of
Improvment.md: four-mode model, capacity validation, runtime/updater separation,
password control, RCON status + console, player list, log source separation and
an audit-log foundation. Basic-Auth is retained for Phase 1; session auth and
roles arrive in Phase 4.

The panel NEVER runs SteamCMD. Game lifecycle uses the pinned runtime image whose
launcher cannot update CS2; updates are the exclusive job of the cs2-updater
maintenance service (see runtime/ and updater/).
"""

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
from flask import Flask, Response, jsonify, render_template, request

import mode_defs

app = Flask(__name__)


class _LazyDockerClient:
    """Defer docker.from_env() until first use so importing this module never
    requires a running Docker daemon. The rebuild health-check imports app.py in
    an isolated container with no docker socket; eager connection there would
    always fail the check (see api_panel_rebuild)."""

    _client = None

    def _get(self):
        if _LazyDockerClient._client is None:
            _LazyDockerClient._client = docker.from_env()
        return _LazyDockerClient._client

    def __getattr__(self, name):
        return getattr(self._get(), name)


client = _LazyDockerClient()

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
USERNAME = os.environ.get("PANEL_USERNAME", "admin")
PASSWORD = os.environ.get("PANEL_PASSWORD", "")

DATA_DIR = Path(os.environ.get("PANEL_DATA_DIR", "/data"))
# manager/modes — the mode definitions (mode.json + cfg + plugins + utils).
# PANEL_PROFILES_DIR is the pre-rename name, still honoured so a stale panel
# container/env keeps booting.
MODES_ROOT = Path(os.environ.get("PANEL_MODES_DIR")
                  or os.environ.get("PANEL_PROFILES_DIR")
                  or "/modes")
# Live per-mode settings the panel writes (distinct from the definitions above).
MODES_DIR = DATA_DIR / "modes"
AUDIT_DIR = DATA_DIR / "audit"
SERVER_JSON = DATA_DIR / "server.json"
SECRETS_JSON = DATA_DIR / "secrets.json"
CONSOLE_HISTORY_JSON = DATA_DIR / "console_history.json"

RCON_PORT = int(os.environ.get("CS2_PORT", "27015"))
RCON_PASSWORD = os.environ.get("CS2_RCON_PASSWORD", "")
RCON_APPLY_TIMEOUT = int(os.environ.get("RCON_APPLY_TIMEOUT", "90"))
LOG_TAIL_DEFAULT = int(os.environ.get("LOG_TAIL_DEFAULT", "300"))
CONSOLE_COMMAND_MAX_LENGTH = 256

# Maintenance (Phase 3) — host paths and images for orchestrating containers.
PROJECT_DIR = Path(os.environ.get("PANEL_PROJECT_DIR", "/project"))
SERVER_DIR = Path(os.environ.get("PANEL_SERVER_DIR", "/server"))
BACKUPS_DIR = PROJECT_DIR / "backups"
# manager/shared — plugins declared with "shared": true in a mode manifest
# (PanelBridge: one built copy, mounted into every mode).
SHARED_DIR = PROJECT_DIR / "shared"
CS2_DATA_PATH_HOST = os.environ.get("CS2_DATA_PATH", "")
MANAGER_PATH_HOST = os.environ.get("MANAGER_PATH", "")
UPDATER_IMAGE = os.environ.get("UPDATER_IMAGE", "cs2-manager-updater:pinned")
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "cs2-server")
UPDATER_CONFIRM_PHRASE = "UPDATE CS2"

ALLOWED_MAPS = [
    item.strip().lower()
    for item in os.environ.get(
        "CS2_ALLOWED_MAPS",
        "de_ancient,de_anubis,de_dust2,de_inferno,de_mirage,de_nuke,de_overpass,de_train,de_vertigo",
    ).split(",")
    if item.strip()
]

# --------------------------------------------------------------------------- #
# Mode registry — derived from manager/modes/<mode-id>/mode.json
#
# The panel hard-codes no mode, plugin, mount or quick-action list. Every mode
# declares its container, its main plugin, its utils, its bind mounts, its
# settings defaults and its whitelisted RCON actions in its own manifest
# (see mode_defs.py); adding a plugin to a mode is a manifest change plus the
# matching bind mount in compose.yml, then a panel restart.
# --------------------------------------------------------------------------- #
MODE_DEFS, MODE_DEF_ERRORS = mode_defs.load_definitions(MODES_ROOT)
for _problem in MODE_DEF_ERRORS:
    app.logger.error("mode definition rejected: %s", _problem)
if not MODE_DEFS:
    # Never fatal: the panel-rebuild health check imports this module in a
    # container with no modes mount. A real deployment with an empty registry is
    # surfaced by /api/v3/health and verify-mounts instead.
    app.logger.error("No mode definitions found under %s.", MODES_ROOT)

MODES = {
    mode: {
        "label": definition["label"],
        "implementation": definition["implementation"],
        "container": definition["container"],
        "mode_dir": definition["id"],
        "capacity_env": definition["capacity_env"],
        "server_config": definition["server_config"],
        "required_plugins": definition["required_plugins"],
    }
    for mode, definition in MODE_DEFS.items()
}
MODE_ORDER = list(MODE_DEFS)
# Whitelisted per-mode RCON quick actions; the panel never sends UI-supplied text.
MODE_ACTIONS = {mode: definition["actions"] for mode, definition in MODE_DEFS.items()}
DEFAULT_MODE_SETTINGS = {mode: dict(definition["defaults"])
                         for mode, definition in MODE_DEFS.items()}
CONTAINER_TO_MODE = {meta["container"]: mode for mode, meta in MODES.items()}
GAME_CONTAINERS = [meta["container"] for meta in MODES.values()]
UPDATER_CONTAINER = "cs2-updater"
PANEL_CONTAINER = "cs2-panel"


def mode_dir(mode: str) -> Path:
    """Host-side directory of a mode's definition (manager/modes/<id>)."""
    return MODES_ROOT / MODES[mode]["mode_dir"]


# Apply level per field. Fields not listed default to "hot". "map" reloads via
# changelevel; "capacity" is a slot count applied on the next container start.
# max_rounds / freezetime / friendly_fire / bot_quota are hot convars.
APPLY_LEVELS = {
    "map": "map_reload",
    "capacity": "game_restart",
    "max_rounds": "hot",
    "freezetime": "hot",
    "friendly_fire": "hot",
    "bot_quota": "hot",
}

# The Server Config surface is unified to six fields for every mode; each mode's
# manifest owns its defaults and its capacity range (settings.defaults /
# settings.capacity in manager/modes/<id>/mode.json).
CAPACITY_RANGES = {mode: dict(definition["capacity"])
                   for mode, definition in MODE_DEFS.items()}

DEFAULT_SERVER = {
    "hostname": os.environ.get("CS2_SERVERNAME", "CS2 Server"),
    "lan": False, "port": RCON_PORT, "rcon_port": RCON_PORT,
    "friendly_fire": False, "cheats": False, "hibernate": False,
    "logging_level": "on", "access_mode": "public", "last_mode": None,
    "password_policy": "global",
}

# --------------------------------------------------------------------------- #
# Locks and mutable state
# --------------------------------------------------------------------------- #
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

# --------------------------------------------------------------------------- #
# Redaction (secrets must never reach logs, history or audit)
# --------------------------------------------------------------------------- #
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
SECRET_PATTERNS = [
    (re.compile(r"(?i)(\+?rcon_password\s+)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(\+?sv_password\s+)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(\+sv_setsteamaccount\s+)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(SRCDS_TOKEN\s*[=:]\s*)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(CS2_RCONPW\s*[=:]\s*)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(CS2_PW\s*[=:]\s*)(?:\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
]


def redact(text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", text).replace("\x00", "")
    for pattern, replacement in SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
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
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="CS2 Manager"'},
            )
        return fn(*args, **kwargs)

    return wrapper


def current_user() -> str:
    auth = request.authorization
    return (auth.username if auth else "anonymous") or "anonymous"


# --------------------------------------------------------------------------- #
# Atomic JSON persistence
# --------------------------------------------------------------------------- #
def read_json(path: Path, default: dict) -> dict:
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            merged = json.loads(json.dumps(default))
            merged.update(stored)
            return merged
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return json.loads(json.dumps(default))


def write_json(path: Path, payload: dict) -> None:
    with FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        tmp.replace(path)


def load_server() -> dict:
    return read_json(SERVER_JSON, DEFAULT_SERVER)


def save_server(data: dict) -> None:
    write_json(SERVER_JSON, data)


def load_mode(mode: str) -> dict:
    return read_json(MODES_DIR / f"{mode}.json", DEFAULT_MODE_SETTINGS[mode])


def save_mode(mode: str, data: dict) -> None:
    write_json(MODES_DIR / f"{mode}.json", data)


def load_secrets() -> dict:
    return read_json(SECRETS_JSON, {"password_enabled": False, "server_password": "",
                                    "per_mode": {}})


def save_secrets(data: dict) -> None:
    write_json(SECRETS_JSON, data)


# --------------------------------------------------------------------------- #
# Audit log (JSONL per day, secrets redacted)
# --------------------------------------------------------------------------- #
def audit(action: str, result: str, detail: str = "", target: str | None = None,
          job_id: str | None = None) -> None:
    entry = {
        "time": now_iso(),
        "user": current_user() if request else "system",
        "role": "Owner",  # single-role until Phase 4
        "action": action,
        "target": target,
        "result": result,
        "source_ip": (request.remote_addr if request else None),
        "detail": redact(str(detail))[:500],
        "job_id": job_id,
    }
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        with FILE_LOCK:
            with (AUDIT_DIR / f"audit-{day}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        app.logger.warning("audit write failed: %s", exc)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def normalize_map(value: object) -> str:
    name = str(value or "").strip().lower()
    if name not in ALLOWED_MAPS:
        raise ValueError("Map is not in the allowed map list")
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError("Invalid map name")
    return name


def validate_mode_settings(mode: str, settings: dict) -> dict:
    """Validate + normalize the seven unified Server Config fields.

    Every mode exposes the same surface: map, capacity, max_rounds, freezetime,
    friendly_fire, bot_quota. Raises ValueError on failure. Unknown legacy keys
    are dropped so old on-disk settings collapse to the new shape.
    """
    defaults = DEFAULT_MODE_SETTINGS[mode]
    out = {"map": normalize_map(settings.get("map", defaults["map"]))}

    cap = int(settings.get("capacity", defaults["capacity"]))
    cap_range = CAPACITY_RANGES[mode]
    if not cap_range["min"] <= cap <= cap_range["max"]:
        raise ValueError(f"Capacity must be between {cap_range['min']} and {cap_range['max']}")
    out["capacity"] = cap

    mr = int(settings.get("max_rounds", defaults["max_rounds"]))
    if not 1 <= mr <= 120:
        raise ValueError("Max rounds must be between 1 and 120")
    out["max_rounds"] = mr

    ft = int(settings.get("freezetime", defaults["freezetime"]))
    if not 0 <= ft <= 60:
        raise ValueError("Freeze time must be between 0 and 60 seconds")
    out["freezetime"] = ft

    bq = int(settings.get("bot_quota", defaults["bot_quota"]))
    if not 0 <= bq <= 10:
        raise ValueError("Bots must be between 0 and 10")
    out["bot_quota"] = bq

    out["friendly_fire"] = bool(settings.get("friendly_fire", defaults["friendly_fire"]))
    return out


# --------------------------------------------------------------------------- #
# panel_runtime.cfg generation (Improvment.md section 19)
# --------------------------------------------------------------------------- #
def runtime_cfg_path(mode: str) -> Path:
    return mode_dir(mode) / "cfg" / MODE_DEFS[mode]["startup"]["runtime_cfg"]


def hot_convar_lines(settings: dict) -> list[str]:
    """The four hot convars shared by every mode's runtime cfg / live apply."""
    return [
        f"bot_quota {settings.get('bot_quota', 0)}",
        f"mp_friendlyfire {1 if settings.get('friendly_fire', False) else 0}",
        f"mp_maxrounds {settings.get('max_rounds', 24)}",
        f"mp_freezetime {settings.get('freezetime', 15)}",
    ]


def generate_runtime_cfg(mode: str, settings: dict, password_line: str) -> str:
    lines = [
        "// Generated by CS2 Manager V3. Do not edit — overwritten on Apply.",
        f'echo "[CS2 Manager] Applying {mode} runtime settings"',
        password_line,
        *hot_convar_lines(settings),
    ]
    # Per-mode convars come from the mode manifest (settings.extra_cfg), e.g.
    # MatchZy's autostart on FaceIt or the overtime rule GunGame needs off.
    lines.extend(MODE_DEFS[mode]["extra_cfg"])
    lines.append(f"changelevel {settings['map']}")
    return "\n".join(lines) + "\n"


def write_runtime_cfg(mode: str, settings: dict) -> None:
    sec = load_secrets()
    if sec.get("password_enabled") and sec.get("server_password"):
        password_line = f'sv_password "{sec["server_password"]}"'
    else:
        password_line = 'sv_password ""'
    path = runtime_cfg_path(mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(generate_runtime_cfg(mode, settings, password_line),
                   encoding="utf-8", newline="\n")
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# Source RCON client
# --------------------------------------------------------------------------- #
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
        if self.sock is None:
            raise RuntimeError("RCON socket is not connected")
        chunks, remaining = [], length
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise ConnectionError("RCON connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _send_packet(self, packet_type, body):
        if self.sock is None:
            raise RuntimeError("RCON socket is not connected")
        self.request_id = (self.request_id + 1) & 0x7FFFFFFF
        payload = struct.pack("<ii", self.request_id, packet_type) + body.encode("utf-8") + b"\x00\x00"
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
        request_id = self._send_packet(self.SERVERDATA_AUTH, self.password)
        for _ in range(4):
            response_id, packet_type, _ = self._recv_packet()
            if packet_type == self.SERVERDATA_AUTH_RESPONSE:
                if response_id == -1:
                    raise PermissionError("RCON authentication failed")
                if response_id == request_id:
                    return
        raise PermissionError("RCON authentication response was not received")

    def command(self, command):
        request_id = self._send_packet(self.SERVERDATA_EXECCOMMAND, command)
        responses = []
        for _ in range(6):
            response_id, packet_type, body = self._recv_packet()
            if response_id == request_id and packet_type == self.SERVERDATA_RESPONSE_VALUE:
                responses.append(body)
                break
        return "".join(responses)


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


# --------------------------------------------------------------------------- #
# RCON apply queue (deferred until the server accepts connections)
# --------------------------------------------------------------------------- #
def next_rcon_generation() -> int:
    global RCON_JOB_GENERATION
    with RCON_JOB_LOCK:
        RCON_JOB_GENERATION += 1
        return RCON_JOB_GENERATION


def rcon_generation_current(generation: int) -> bool:
    with RCON_JOB_LOCK:
        return generation == RCON_JOB_GENERATION


def cancel_pending_rcon() -> None:
    next_rcon_generation()


def queue_runtime_apply(mode: str, container: str) -> None:
    """After a (re)start, wait for RCON then exec the freshly written cfg."""
    if not RCON_PASSWORD:
        app.logger.warning(
            "CS2_RCON_PASSWORD is not configured; skipping panel_runtime.cfg apply "
            "for %s to avoid tripping the server's RCON ban protection.", container,
        )
        return

    generation = next_rcon_generation()

    def worker():
        deadline = time.monotonic() + RCON_APPLY_TIMEOUT
        while time.monotonic() < deadline:
            if not rcon_generation_current(generation):
                return
            try:
                rcon_command(container, "exec panel_runtime.cfg", timeout=4.0)
                STATE_TIMESTAMPS["last_successful_start"] = now_iso()
                app.logger.info("Applied panel_runtime.cfg to %s", container)
                return
            except (OSError, RuntimeError, ValueError, PermissionError):
                time.sleep(2)
        app.logger.warning("Runtime apply to %s timed out", container)

    threading.Thread(target=worker, daemon=True, name=f"apply-{mode}").start()


# --------------------------------------------------------------------------- #
# Docker helpers
# --------------------------------------------------------------------------- #
def container_state(name: str) -> dict:
    mode = CONTAINER_TO_MODE.get(name)
    try:
        c = client.containers.get(name)
        c.reload()
        started = c.attrs.get("State", {}).get("StartedAt")
        return {
            "name": name, "mode": mode,
            "label": MODES[mode]["label"] if mode else name,
            "status": c.status, "running": c.status == "running",
            "started_at": started,
            "restart_count": c.attrs.get("RestartCount", 0),
        }
    except NotFound:
        return {"name": name, "mode": mode,
                "label": MODES[mode]["label"] if mode else name,
                "status": "not-created", "running": False,
                "started_at": None, "restart_count": 0}


def all_game_states() -> list[dict]:
    return [container_state(n) for n in GAME_CONTAINERS]


def active_container() -> dict | None:
    return next((s for s in all_game_states() if s["running"]), None)


def stop_others(except_name: str | None = None) -> None:
    for name in GAME_CONTAINERS:
        if name == except_name:
            continue
        try:
            c = client.containers.get(name)
            c.reload()
            if c.status == "running":
                c.stop(timeout=20)
        except NotFound:
            continue


def port_27015_free(except_name: str | None) -> bool:
    for name in GAME_CONTAINERS:
        if name == except_name:
            continue
        try:
            c = client.containers.get(name)
            c.reload()
            if c.status == "running":
                return False
        except NotFound:
            continue
    return True


def container_stats(name: str) -> dict:
    """One-shot CPU/memory sample. Returns {} if unavailable."""
    try:
        c = client.containers.get(name)
        if c.status != "running":
            return {}
        s = c.stats(stream=False)
        cpu = s["cpu_stats"]["cpu_usage"]["total_usage"] - s["precpu_stats"]["cpu_usage"]["total_usage"]
        sys = s["cpu_stats"].get("system_cpu_usage", 0) - s["precpu_stats"].get("system_cpu_usage", 0)
        ncpu = s["cpu_stats"].get("online_cpus") or len(
            s["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]) or [1])
        cpu_pct = (cpu / sys) * ncpu * 100.0 if sys > 0 else 0.0
        mem_used = s["memory_stats"].get("usage", 0)
        mem_limit = s["memory_stats"].get("limit", 0)
        return {
            "cpu_percent": round(cpu_pct, 1),
            "mem_used_mb": round(mem_used / 1048576, 1),
            "mem_limit_mb": round(mem_limit / 1048576, 1),
            "mem_percent": round((mem_used / mem_limit) * 100, 1) if mem_limit else 0.0,
        }
    except (DockerException, KeyError, TypeError, ZeroDivisionError):
        return {}


# --------------------------------------------------------------------------- #
# Player table parsing (RCON `status`)
# --------------------------------------------------------------------------- #
# CS2 `status` player rows are columnar with the name in trailing single quotes:
#   id     time ping loss      state   rate adr name
#    3 03:24   35    0     active 786432 85.1.2.3:27005 'Arik'
# The old quoted layout (id "name" steamid) is also tolerated as a fallback.
STATUS_COUNTS_RE = re.compile(
    r"players\s*:\s*(?P<humans>\d+)\s+humans,\s*(?P<bots>\d+)\s+bots\s*\((?P<max>\d+)\s*max",
    re.IGNORECASE,
)
STATUS_MAP_RE = re.compile(r"\[\s*1:\s*(?P<map>[A-Za-z0-9_]+)\s*\|")
STEAMID_RE = re.compile(r"\[[UG]:\d:\d+\]")
STATUS_QUOTED_RE = re.compile(r'^\s*(\d+)\s+"([^"]*)"\s+(\[?[A-Za-z0-9:_\]]+)')


def parse_current_map(status_output: str) -> str | None:
    m = STATUS_MAP_RE.search(status_output)
    return m.group("map") if m else None


def parse_player_counts(status_output: str) -> dict:
    m = STATUS_COUNTS_RE.search(status_output)
    if not m:
        return {}
    return {"humans": int(m.group("humans")), "bots": int(m.group("bots")),
            "max": int(m.group("max"))}


# PanelBridge plugin output: PP|userid|steamid64|team|ping|isbot|name
TEAM_LABELS = {0: "None", 1: "Spectator", 2: "T", 3: "CT"}
PANEL_PLAYER_RE = re.compile(r"^PP\|(-?\d+)\|(\d+)\|(-?\d+)\|(\d+)\|([01])\|(.*)$")


def parse_panel_players(output: str) -> list[dict] | None:
    """Parse `css_panel_players` output. Returns None if the plugin is absent."""
    if "PANELPLAYERS_BEGIN" not in output:
        return None
    players = []
    for line in output.splitlines():
        m = PANEL_PLAYER_RE.match(line.strip())
        if not m:
            continue
        userid, steam64, team, ping, isbot, name = m.groups()
        s64 = int(steam64)
        players.append({
            "userid": int(userid),
            "steamid64": str(s64) if s64 != 0 else None,
            "team": int(team),
            "team_label": TEAM_LABELS.get(int(team), "?"),
            "ping": int(ping),
            "bot": isbot == "1",
            "name": name,
        })
    return players


def parse_players(status_output: str) -> list[dict]:
    players = []
    in_players = False
    for raw in status_output.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if "players---" in line or stripped.startswith("id "):
            in_players = True
            continue
        if stripped == "#end":
            break
        if not in_players:
            continue
        id_m = re.match(r"\s*(\d+)\s", line)
        if not id_m:
            continue
        userid = int(id_m.group(1))
        name_m = re.search(r"'([^']*)'\s*$", line)
        quoted_m = STATUS_QUOTED_RE.match(line)
        if name_m:
            name = name_m.group(1)
            head = line[:name_m.start()]
        elif quoted_m:
            name = quoted_m.group(2)
            head = line[:quoted_m.start(2)]
        else:
            continue
        # Skip reserved/negotiating placeholder slots with no real occupant.
        if userid >= 65535 and not name:
            continue
        if "challenging" in line and not name:
            continue
        steam_m = STEAMID_RE.search(line)
        if steam_m and name.startswith(steam_m.group(0)):
            name = name[len(steam_m.group(0)):].strip()
        tokens = head.split()
        # Columns after userid: time, ping, loss, state ... ping is 3rd token.
        ping = int(tokens[2]) if len(tokens) >= 3 and tokens[2].isdigit() else None
        players.append({
            "userid": userid,
            "name": name,
            "steamid": steam_m.group(0) if steam_m else None,
            "ping": ping,
            "bot": ("BOT" in line) or (quoted_m is not None and quoted_m.group(3) == "BOT"),
        })
    return players


# --------------------------------------------------------------------------- #
# Operational state (Improvment.md section 6.1)
# --------------------------------------------------------------------------- #
def operational_state(active: dict | None) -> str:
    if active is None:
        return "Stopped"
    if not rcon_reachable(active["name"]):
        return "StartingGame"
    return "Ready"


# --------------------------------------------------------------------------- #
# Console command risk classification (Improvment.md section 13.3)
# --------------------------------------------------------------------------- #
BLOCKED_COMMANDS = {"quit", "exit", "_restart", "crash"}
DANGEROUS_PREFIXES = ("sv_password", "rcon_password", "sv_cheats")
DISRUPTIVE_PREFIXES = ("mp_restartgame", "changelevel", "map", "kickid", "kick",
                       "quit", "_restart", "css_endmatch", "css_restart")


def classify_command(command: str) -> str:
    head = command.strip().split()[0].lower() if command.strip() else ""
    if head in BLOCKED_COMMANDS:
        return "Blocked"
    if any(command.lower().startswith(p) for p in DANGEROUS_PREFIXES):
        return "Dangerous"
    if any(head == p or command.lower().startswith(p) for p in DISRUPTIVE_PREFIXES):
        return "Disruptive"
    if head in ("status", "users", "meta", "css_plugins", "version", "stats"):
        return "ReadOnly"
    return "Normal"


# --------------------------------------------------------------------------- #
# Startup seeding
# --------------------------------------------------------------------------- #
def ensure_data_files() -> None:
    if not SERVER_JSON.exists():
        save_server(DEFAULT_SERVER)
    for mode in MODES:
        if not (MODES_DIR / f"{mode}.json").exists():
            save_mode(mode, DEFAULT_MODE_SETTINGS[mode])
    if not SECRETS_JSON.exists():
        # Seed password state from CS2_PASSWORD env if present.
        env_pw = os.environ.get("CS2_PASSWORD", "")
        save_secrets({"password_enabled": bool(env_pw),
                      "server_password": env_pw, "per_mode": {}})
    for mode in MODES:
        try:
            write_runtime_cfg(mode, load_mode(mode))
        except (ValueError, OSError) as exc:
            app.logger.warning("seed runtime cfg %s failed: %s", mode, exc)


# --------------------------------------------------------------------------- #
# Background jobs (Improvment.md section 23)
# --------------------------------------------------------------------------- #
JOBS: dict[str, "Job"] = {}
JOBS_LOCK = threading.Lock()
JOB_MAX = 50


class Job:
    def __init__(self, jtype: str, user: str):
        self.id = uuid.uuid4().hex[:12]
        self.type = jtype
        self.status = "Queued"          # Queued|Running|Succeeded|Failed|Cancelled
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
        line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  {redact(str(text))}"
        with self._lock:
            self.log.append(line)
            if len(self.log) > 2000:
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
        with self._lock:
            d = {"id": self.id, "type": self.type, "status": self.status,
                 "step": self.step, "percent": self.percent, "start": self.start,
                 "end": self.end, "user": self.user, "result": self.result,
                 "error": self.error, "rollback_status": self.rollback_status}
            if include_log:
                d["log"] = list(self.log)
            return d


def start_job(jtype: str, worker) -> Job:
    job = Job(jtype, current_user() if request else "system")
    with JOBS_LOCK:
        JOBS[job.id] = job
        # Trim oldest finished jobs.
        if len(JOBS) > JOB_MAX:
            for jid in sorted(JOBS, key=lambda k: JOBS[k].start)[:len(JOBS) - JOB_MAX]:
                if JOBS[jid].status in ("Succeeded", "Failed", "Cancelled"):
                    JOBS.pop(jid, None)

    def run():
        job.set(status="Running")
        try:
            worker(job)
            if job.status == "Running":
                job.set(status="Succeeded", percent=100)
            job.end = now_iso()
        except Exception as exc:  # noqa: BLE001 - jobs must never crash the worker
            job.set(status="Failed")
            job.error = str(exc)
            job.end = now_iso()
            job.emit(f"FAILED: {exc}")
        audit(f"job.{jtype}", job.status.lower(), f"job={job.id}", job_id=job.id)

    threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
    return job


# --------------------------------------------------------------------------- #
# Maintenance helpers
# --------------------------------------------------------------------------- #
def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def run_updater_container(job: Job, updater_mode: str) -> int:
    """Run the isolated updater image (the only place SteamCMD runs), streaming
    its output into the job log. Returns the container exit code."""
    if not CS2_DATA_PATH_HOST:
        raise RuntimeError("CS2_DATA_PATH is not configured for the panel")
    name = f"cs2-updater-job-{job.id}"
    job.emit(f"Launching updater ({updater_mode}) as {name}")
    try:
        client.containers.get(name).remove(force=True)
    except NotFound:
        pass
    container = client.containers.run(
        UPDATER_IMAGE,
        detach=True, name=name, network_mode="none",
        environment={"CS2_UPDATER_MODE": updater_mode,
                     "CS2_UPDATER_CONFIRM": UPDATER_CONFIRM_PHRASE},
        volumes={CS2_DATA_PATH_HOST: {"bind": "/home/steam/cs2-dedicated", "mode": "rw"}},
    )
    try:
        for chunk in container.logs(stream=True, follow=True):
            job.emit(chunk.decode("utf-8", errors="replace").rstrip())
        result = container.wait()
        code = result.get("StatusCode", -1)
        job.emit(f"Updater exited with code {code}")
        return code
    finally:
        try:
            container.remove(force=True)
        except DockerException:
            pass


def make_backup(job: Job, scope: str = "config") -> Path:
    """Timestamped config backup (never the full 69GB install)."""
    dest = BACKUPS_DIR / f"{scope}-{timestamp_slug()}"
    dest.mkdir(parents=True, exist_ok=True)
    job.emit(f"Backup -> {dest.name}")
    for rel in ("compose.yml", ".env", ".env.example"):
        src = PROJECT_DIR / rel
        if src.exists():
            shutil.copy2(src, dest / rel)
            job.emit(f"  + {rel}")
    for rel in ("panel", "modes", "data", "runtime", "updater", "shared"):
        src = PROJECT_DIR / rel
        if src.exists():
            shutil.copytree(src, dest / rel,
                            ignore=shutil.ignore_patterns("*.tmp", "__pycache__", "bin", "obj"),
                            dirs_exist_ok=True)
            job.emit(f"  + {rel}/")
    # gameinfo.gi from the read-only server mount.
    gameinfo = SERVER_DIR / "game" / "csgo" / "gameinfo.gi"
    if gameinfo.exists():
        (dest / "server-critical").mkdir(exist_ok=True)
        shutil.copy2(gameinfo, dest / "server-critical" / "gameinfo.gi")
        job.emit("  + gameinfo.gi")
    STATE_TIMESTAMPS["last_backup"] = now_iso()
    return dest


UNKNOWN_COMMAND_RE = re.compile(r"unknown command", re.IGNORECASE)


def command_unknown(output: str) -> bool:
    """True when the engine rejected the command, i.e. its provider is not loaded.

    The reply echoes the command name, so any substring test against that name
    (`"plugin" in "Unknown command 'css_plugins'!"`) would read as healthy.
    """
    return bool(UNKNOWN_COMMAND_RE.search(output or ""))


def gameinfo_has_metamod() -> bool | None:
    gameinfo = SERVER_DIR / "game" / "csgo" / "gameinfo.gi"
    try:
        return "csgo/addons/metamod" in gameinfo.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def verify_mounts() -> dict:
    """Read-only check that every bind source the mode manifests declare exists.

    Sources come from manager/modes/<id>/mode.json, so a plugin added to a mode is
    checked here the moment it is declared — there is no second list to maintain.
    """
    checks: dict[str, bool | None] = {}
    checks["modes:definitions"] = bool(MODE_DEFS) and not MODE_DEF_ERRORS

    for mode, definition in MODE_DEFS.items():
        mdir = mode_dir(mode)
        for key in ("mode_cfg", "runtime_cfg"):
            name = definition["startup"][key]
            checks[f"{mode}:{name}"] = (mdir / "cfg" / name).exists()
        for row in mode_defs.declared_mounts(definition):
            src = mode_defs.mount_source_path(row, mdir, SHARED_DIR)
            leaf = row["source"].rsplit("/", 1)[-1]
            label = f"{mode}:{row['owner']}" if leaf == row["owner"] else f"{mode}:{row['owner']}:{leaf}"
            checks[label] = src.is_file() if row["kind"] == "file" else src.is_dir()
        # In-house plugins also declare the C# project they are built from. It is
        # never mounted into the container, only checked so a missing source tree
        # is visible before someone needs to rebuild the plugin.
        for plugin in definition["plugins"]:
            if plugin["build"]:
                project = mode_defs.build_project_path(plugin["build"], mdir, SHARED_DIR)
                checks[f"{mode}:{plugin['name']}:src"] = project.is_dir()
    checks["server:gameinfo"] = (SERVER_DIR / "game" / "csgo" / "gameinfo.gi").exists()
    checks["server:cs2_binary"] = (SERVER_DIR / "game" / "bin" / "linuxsteamrt64" / "cs2").exists()
    checks["gameinfo_metamod_line"] = gameinfo_has_metamod()
    checks["data:server.json"] = SERVER_JSON.exists()
    return checks


def restart_previous_mode(job: Job, mode: str) -> bool:
    """Bring a mode back up after maintenance and verify readiness over RCON."""
    job.emit(f"Restarting previous mode: {mode}")
    try:
        _start_mode(mode, restart_if_running=True)
    except (ValueError, RuntimeError, DockerException, NotFound) as exc:
        job.emit(f"Restart failed: {exc}")
        return False
    container = MODES[mode]["container"]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if rcon_reachable(container):
            job.emit("RCON reachable.")
            try:
                job.emit("status: " + rcon_command(container, "status", 4.0)[:200])
                job.emit("meta list: " + rcon_command(container, "meta list", 4.0)[:200])
                job.emit("css_plugins: " + rcon_command(container, "css_plugins list", 4.0)[:200])
            except (OSError, RuntimeError, ValueError, PermissionError):
                pass
            return True
        time.sleep(3)
    job.emit("Timed out waiting for RCON after restart.")
    return False


# =========================================================================== #
# ROUTES
# =========================================================================== #
@app.get("/")
@require_auth
def index():
    return render_template("index.html")


# ------------------------------------------------------------- status/health
@app.get("/api/v3/status")
@require_auth
def api_status():
    try:
        states = all_game_states()
        active = next((s for s in states if s["running"]), None)
        server = load_server()
        sec = load_secrets()
        return jsonify({
            "ok": True,
            "operational_state": operational_state(active),
            "containers": states,
            "active": active,
            "server": {k: v for k, v in server.items()},
            "password": {"enabled": bool(sec.get("password_enabled")),
                         "policy": server.get("password_policy", "global")},
            "modes": {m: load_mode(m) for m in MODES},
            "mode_order": MODE_ORDER,
            "mode_defaults": {m: DEFAULT_MODE_SETTINGS[m] for m in MODES},
            "mode_meta": {m: {"label": MODES[m]["label"],
                              "implementation": MODES[m]["implementation"],
                              "container": MODES[m]["container"],
                              "server_config": MODES[m]["server_config"],
                              "capacity": CAPACITY_RANGES[m],
                              "plugins": [{"name": p["name"], "role": p["role"],
                                           "required": p["required"]}
                                          for p in MODE_DEFS[m]["plugins"]],
                              "actions": [{k: a[k] for k in mode_defs.ACTION_PUBLIC_FIELDS}
                                          for a in MODE_ACTIONS.get(m, [])]}
                          for m in MODES},
            "mode_definition_errors": MODE_DEF_ERRORS,
            "apply_levels": APPLY_LEVELS,
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
        "single_active_service": sum(1 for s in all_game_states() if s["running"]) <= 1,
        "rcon": False, "metamod": None, "counterstrikesharp": None,
        "required_plugins": {}, "map": None, "players": None,
    }
    stats = {}
    if active:
        checks["rcon"] = rcon_reachable(active["name"])
        stats = container_stats(active["name"])
        if checks["rcon"]:
            try:
                meta = rcon_command(active["name"], "meta list", timeout=4.0)
                # Metamod is loaded if it reports its plugin listing (which always
                # includes the CounterStrikeSharp Metamod shim on this install).
                checks["metamod"] = not command_unknown(meta) and (
                    bool(re.search(r"[Ll]isting\s+\d+\s+plugin", meta))
                    or "CounterStrikeSharp" in meta)
                css = rcon_command(active["name"], "css_plugins list", timeout=4.0)
                # Require evidence of a real listing. When CounterStrikeSharp is not
                # loaded the engine answers "Unknown command 'css_plugins'!", whose
                # text contains "plugin" — a bare substring test reports healthy.
                # Loaded output is "List of all plugins currently loaded by
                # CounterStrikeSharp: N plugins loaded." followed by [#N:LOADED] rows,
                # and stays truthful at zero plugins (CSS itself is what is checked).
                checks["counterstrikesharp"] = not command_unknown(css) and bool(
                    re.search(r"\[#\d+:|plugins?\s+loaded|loaded by CounterStrikeSharp",
                              css, re.IGNORECASE))
                combined = (meta + "\n" + css).lower()
                definition = MODE_DEFS[active["mode"]]
                for plug in definition["required_plugins"]:
                    aliases = definition["plugin_aliases"][plug]
                    checks["required_plugins"][plug] = any(a in combined for a in aliases)
                status_out = rcon_command(active["name"], "status", timeout=4.0)
                checks["map"] = parse_current_map(status_out)
                checks["players"] = parse_player_counts(status_out).get("humans")
            except (OSError, RuntimeError, ValueError, PermissionError) as exc:
                checks["rcon_error"] = str(exc)
    return jsonify({"ok": True, "active_mode": active["mode"] if active else None,
                    "checks": checks, "stats": stats})


@app.get("/api/v3/metrics")
@require_auth
def api_metrics():
    active = active_container()
    return jsonify({"ok": True, "stats": container_stats(active["name"]) if active else {}})


# ---------------------------------------------------------- server lifecycle
def _start_mode(mode: str, restart_if_running: bool) -> dict:
    meta = MODES[mode]
    target = meta["container"]
    settings = validate_mode_settings(mode, load_mode(mode))
    save_mode(mode, settings)
    write_runtime_cfg(mode, settings)

    server = load_server()
    server["last_mode"] = mode
    save_server(server)

    with OPERATION_LOCK:
        stop_others(target)
        if not port_27015_free(target):
            raise RuntimeError("Port 27015 is still in use by another game service")
        c = client.containers.get(target)
        c.reload()
        if c.status == "running":
            if restart_if_running:
                c.restart(timeout=20)
        else:
            c.start()
    queue_runtime_apply(mode, target)
    return settings


@app.post("/api/v3/server/start")
@require_auth
def api_server_start():
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode") or load_server().get("last_mode")
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown or unset mode"}), 400
    try:
        settings = _start_mode(mode, restart_if_running=False)
        audit("server.start", "ok", f"mode={mode}", target=mode)
        return jsonify({"ok": True, "mode": mode, "settings": settings})
    except NotFound:
        audit("server.start", "fail", f"container missing for {mode}", target=mode)
        return jsonify({"ok": False, "error": "Container not created. Run migrate/start script."}), 409
    except (ValueError, RuntimeError) as exc:
        audit("server.start", "fail", str(exc), target=mode)
        return jsonify({"ok": False, "error": str(exc)}), 400
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/v3/server/stop")
@require_auth
def api_server_stop():
    try:
        cancel_pending_rcon()
        with OPERATION_LOCK:
            stop_others(None)
        audit("server.stop", "ok")
        return jsonify({"ok": True})
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/v3/server/restart")
@require_auth
def api_server_restart():
    """Restart only the active game runtime. Never runs SteamCMD."""
    try:
        active = active_container()
        if not active:
            return jsonify({"ok": False, "error": "No game mode is running"}), 409
        with OPERATION_LOCK:
            client.containers.get(active["name"]).restart(timeout=20)
        queue_runtime_apply(active["mode"], active["name"])
        audit("server.restart", "ok", target=active["mode"])
        return jsonify({"ok": True, "mode": active["mode"]})
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/v3/server/refresh")
@require_auth
def api_server_refresh():
    # Refresh is display-only; the client re-fetches status. No side effects.
    return jsonify({"ok": True})


# ------------------------------------------------------------------- modes
@app.get("/api/v3/modes")
@require_auth
def api_modes():
    return jsonify({"ok": True, "modes": {m: load_mode(m) for m in MODES},
                    "order": MODE_ORDER,
                    "meta": {m: {"label": MODES[m]["label"],
                                 "implementation": MODES[m]["implementation"]}
                             for m in MODES}})


@app.get("/api/v3/modes/<mode>")
@require_auth
def api_mode_get(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    settings = load_mode(mode)
    definition = MODE_DEFS[mode]
    resp = {"ok": True, "mode": mode, "settings": settings,
            "meta": {"label": MODES[mode]["label"],
                     "implementation": MODES[mode]["implementation"],
                     "container": definition["container"],
                     "game_alias": definition["startup"]["game_alias"],
                     "capacity": CAPACITY_RANGES[mode],
                     "plugins": [{"name": p["name"], "role": p["role"],
                                  "required": p["required"]}
                                 for p in definition["plugins"]]}}
    return jsonify(resp)


@app.put("/api/v3/modes/<mode>/settings")
@require_auth
def api_mode_settings(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    payload = request.get_json(silent=True) or {}
    current = load_mode(mode)
    current.update(payload)
    try:
        validated = validate_mode_settings(mode, current)
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    save_mode(mode, validated)
    audit("mode.settings", "ok", f"{mode}: {redact(json.dumps(payload))}", target=mode)
    return jsonify({"ok": True, "mode": mode, "settings": validated})


@app.post("/api/v3/modes/<mode>/apply")
@require_auth
def api_mode_apply(mode):
    """Write runtime cfg and hot-apply over RCON if this mode is active."""
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    try:
        settings = validate_mode_settings(mode, load_mode(mode))
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    save_mode(mode, settings)
    write_runtime_cfg(mode, settings)

    active = active_container()
    applied_hot = False
    map_reloaded = False
    if active and active["mode"] == mode and rcon_reachable(active["name"]):
        try:
            # Push the hot convars directly instead of exec'ing the cfg, so a
            # convar-only change never forces a map reload (the cfg ends with
            # changelevel). Capacity is not hot — it lands on the next start.
            for line in hot_convar_lines(settings):
                rcon_command(active["name"], line, timeout=5.0)
            # Only reload the map when it actually differs from what is running.
            try:
                live_map = parse_current_map(
                    rcon_command(active["name"], "status", timeout=4.0))
            except (OSError, RuntimeError, ValueError, PermissionError):
                live_map = None
            if live_map and live_map != settings["map"]:
                rcon_command(active["name"], f"changelevel {settings['map']}", timeout=5.0)
                map_reloaded = True
            applied_hot = True
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            app.logger.warning("hot apply failed: %s", exc)
    STATE_TIMESTAMPS["last_config_apply"] = now_iso()
    audit("mode.apply", "ok", f"mode={mode} hot={applied_hot} map_reload={map_reloaded}",
          target=mode)
    return jsonify({"ok": True, "mode": mode, "applied_hot": applied_hot,
                    "map_reloaded": map_reloaded,
                    "note": "capacity slot count applies on next start/recreate"})


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


@app.get("/api/v3/modes/<mode>/actions")
@require_auth
def api_mode_actions(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    return jsonify({"ok": True, "mode": mode,
                    "actions": [{k: a[k] for k in mode_defs.ACTION_PUBLIC_FIELDS}
                                for a in MODE_ACTIONS.get(mode, [])]})


@app.post("/api/v3/modes/<mode>/action")
@require_auth
def api_mode_action(mode):
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    key = (request.get_json(silent=True) or {}).get("action")
    action = next((a for a in MODE_ACTIONS.get(mode, []) if a["key"] == key), None)
    if not action:
        return jsonify({"ok": False, "error": "Unknown action for this mode"}), 400

    active = active_container()
    if not active or active["mode"] != mode:
        return jsonify({"ok": False, "error": f"{MODES[mode]['label']} is not the active mode"}), 409
    if not RCON_PASSWORD:
        return jsonify({"ok": False, "error": "CS2_RCON_PASSWORD is not configured"}), 500
    try:
        out = rcon_command(active["name"], action["cmd"], timeout=6.0)
        audit("mode.action", "ok", f"{mode}:{key} -> {action['cmd']}", target=mode)
        return jsonify({"ok": True, "action": key, "command": action["cmd"],
                        "output": redact(out)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        audit("mode.action", "fail", f"{mode}:{key}: {exc}", target=mode)
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/v3/modes/<mode>/preview")
@require_auth
def api_mode_preview(mode):
    """Return the change set (old/new/apply-level/interruption) before applying."""
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 404
    pending = request.get_json(silent=True) or {}
    saved = load_mode(mode)
    changes = []
    for field, new_val in pending.items():
        old_val = saved.get(field)
        if old_val == new_val:
            continue
        level = APPLY_LEVELS.get(field, "hot")
        changes.append({
            "field": field, "old": old_val, "new": new_val,
            "apply_level": level,
            "map_reload": level == "map_reload",
            "game_restart": level == "game_restart",
            "disconnects_players": level in ("map_reload", "game_restart"),
        })
    highest = "hot"
    for c in changes:
        if c["apply_level"] == "game_restart":
            highest = "game_restart"
        elif c["apply_level"] == "map_reload" and highest != "game_restart":
            highest = "map_reload"
    return jsonify({"ok": True, "mode": mode, "changes": changes,
                    "highest_apply_level": highest})


@app.post("/api/v3/modes/switch")
@require_auth
def api_mode_switch():
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode")
    if mode not in MODES:
        return jsonify({"ok": False, "error": "Unknown mode"}), 400
    try:
        settings = _start_mode(mode, restart_if_running=True)
        audit("mode.switch", "ok", target=mode)
        return jsonify({"ok": True, "mode": mode, "settings": settings})
    except NotFound:
        return jsonify({"ok": False, "error": "Container not created"}), 409
    except (ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# --------------------------------------------------------------------------- #
# Superheroes: HeroShift skill roster + plugin config (skillsInfo.json / config.json)
# Safe-edit only. HeroShift is the stock Juzlus plugin — it does NOT expose the
# per-player hero query/force console protocol the old bespoke HeroRound fork had,
# so the panel manages the skill roster + a few config toggles and issues
# HeroShift's real console commands (css_reload / css_next_skill).
# --------------------------------------------------------------------------- #
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
# Rarity vocabulary HeroShift ships with (weights skill draw chance).
SKILL_RARITIES = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"]

# config.json boolean toggles the panel may edit (snake_case -> JSON key).
_HS_CONFIG_BOOLS = {
    "your_skill_chat_info": "YourSkillChatInfo",
    "killer_skill_chat_info": "KillerSkillChatInfo",
    "teammate_skill_chat_info": "TeamMateSkillChatInfo",
    "summary_after_round": "SummaryAfterTheRound",
    "enable_bot_skills": "EnableBotSkills",
    "disable_skills_on_round_end": "DisableSkillsOnRoundEnd",
}
_HS_CONFIG_FLOATS = {  # snake_case -> (json_key, min, max)
    "skill_time_before_start": ("SkillTimeBeforeStart", 0.0, 30.0),
    "skill_description_duration": ("SkillDescriptionDuration", -1.0, 60.0),
}


def mode_config_path(mode: str, name: str) -> Path:
    """Host path of a config file the mode manifest declares under `configs`."""
    definition = MODE_DEFS.get(mode)
    entry = next((c for c in definition["configs"] if c["name"] == name), None) if definition else None
    if entry is None:
        raise FileNotFoundError(f"{mode} does not declare a config named {name!r} in mode.json")
    return mode_defs.mount_source_path(entry, mode_dir(mode), SHARED_DIR)


def superheroes_skills_path() -> Path:
    return mode_config_path("superheroes", "skillsInfo.json")


def superheroes_hsconfig_path() -> Path:
    return mode_config_path("superheroes", "config.json")


def read_skills_config() -> list:
    """Read skillsInfo.json (raises FileNotFoundError / JSONDecodeError on failure)."""
    return json.loads(superheroes_skills_path().read_text(encoding="utf-8"))


def read_hs_config() -> dict:
    """Read HeroShift config.json (raises FileNotFoundError / JSONDecodeError)."""
    return json.loads(superheroes_hsconfig_path().read_text(encoding="utf-8"))


def _skills_view(skills: list, cfg: dict) -> dict:
    settings = {snake: bool(cfg.get(jkey, False)) for snake, jkey in _HS_CONFIG_BOOLS.items()}
    for snake, (jkey, _lo, _hi) in _HS_CONFIG_FLOATS.items():
        settings[snake] = float(cfg.get(jkey) or 0.0)
    rows = [{
        "name": s.get("Name", ""),
        "active": bool(s.get("Active", False)),
        "rarity": s.get("Rarity", "Common"),
        "max_per_server": int(s.get("MaxPerServer", -1)),
        "only_team": int(s.get("OnlyTeam", 0)),
        "needs_teammates": bool(s.get("NeedsTeammates", False)),
        "color": s.get("Color", ""),
        "required_permission": s.get("RequiredPermission", ""),
    } for s in skills if isinstance(s, dict) and s.get("Name")]
    rows.sort(key=lambda r: r["name"].casefold())
    return {"settings": settings, "skills": rows, "rarities": SKILL_RARITIES,
            "active_count": sum(1 for r in rows if r["active"]), "total": len(rows)}


def _apply_skill_edits(skills: list, cfg: dict, payload: dict) -> None:
    """Apply only the safe operator surface: config toggles + per-skill
    Active / Rarity / MaxPerServer. Skill mechanics stay as shipped."""
    settings_in = payload.get("settings") or {}
    for snake, jkey in _HS_CONFIG_BOOLS.items():
        if snake in settings_in:
            cfg[jkey] = bool(settings_in[snake])
    for snake, (jkey, lo, hi) in _HS_CONFIG_FLOATS.items():
        if snake in settings_in:
            value = float(settings_in[snake])
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{snake} must be between {lo:g} and {hi:g}")
            cfg[jkey] = value

    edits = {e["name"]: e for e in (payload.get("skills") or []) if isinstance(e, dict) and e.get("name")}
    by_name = {s.get("Name"): s for s in skills if isinstance(s, dict)}
    for name, edit in edits.items():
        skill = by_name.get(name)
        if skill is None:
            raise ValueError(f"Unknown skill '{name}'")
        unknown = set(edit) - {"name", "active", "rarity", "max_per_server"}
        if unknown:
            raise ValueError(f"'{name}' contains unsupported fields: {', '.join(sorted(unknown))}")
        if "active" in edit:
            skill["Active"] = bool(edit["active"])
        if "rarity" in edit:
            rarity = str(edit["rarity"])
            if rarity not in SKILL_RARITIES:
                raise ValueError(f"'{name}' has invalid rarity '{rarity}'")
            skill["Rarity"] = rarity
        if "max_per_server" in edit:
            mps = int(edit["max_per_server"])
            if not -1 <= mps <= 32:
                raise ValueError(f"'{name}' MaxPerServer must be between -1 (unlimited) and 32")
            skill["MaxPerServer"] = mps


def _superheroes_active():
    active = active_container()
    return active if active and active["mode"] == "superheroes" else None


def _backup_and_write(path: Path, data) -> str | None:
    """Backup <name>.bak-<ts> (keep 10) then atomic-write JSON. Returns backup name."""
    backup = None
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        old = sorted(path.parent.glob(f"{path.name}.bak-*"))
        for stale in old[:-10]:
            try:
                stale.unlink()
            except OSError:
                pass
    write_json(path, data)  # atomic tmp + replace
    return backup.name if backup else None


@app.get("/api/v3/modes/superheroes/skills")
@require_auth
def api_skill_roster():
    try:
        skills, cfg = read_skills_config(), read_hs_config()
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        return jsonify({"ok": False, "error": f"Cannot read HeroShift config: {exc}"}), 500
    return jsonify({"ok": True, **_skills_view(skills, cfg)})


@app.put("/api/v3/modes/superheroes/skills")
@require_auth
def api_skill_roster_save():
    payload = request.get_json(silent=True) or {}
    try:
        skills, cfg = read_skills_config(), read_hs_config()
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        return jsonify({"ok": False, "error": f"Cannot read HeroShift config: {exc}"}), 500
    try:
        _apply_skill_edits(skills, cfg, payload)
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        skills_bak = _backup_and_write(superheroes_skills_path(), skills)
        _backup_and_write(superheroes_hsconfig_path(), cfg)
    except OSError as exc:
        return jsonify({"ok": False, "error": f"Backup/write failed: {exc}"}), 500

    reloaded = False
    active = _superheroes_active()
    if active and rcon_reachable(active["name"]):
        try:
            rcon_command(active["name"], "css_reload", timeout=6.0)
            reloaded = True
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            app.logger.warning("HeroShift reload failed: %s", exc)
    audit("superheroes.roster.save", "ok",
          f"skills={len(payload.get('skills') or [])} reloaded={reloaded}", target="superheroes")
    return jsonify({"ok": True, "reloaded": reloaded, "backup": skills_bak,
                    **_skills_view(skills, cfg)})


@app.post("/api/v3/modes/superheroes/skills/reload")
@require_auth
def api_skill_reload():
    active = _superheroes_active()
    if not active:
        return jsonify({"ok": False, "error": "Superheroes is not the active mode"}), 409
    if not RCON_PASSWORD:
        return jsonify({"ok": False, "error": "CS2_RCON_PASSWORD is not configured"}), 500
    try:
        out = rcon_command(active["name"], "css_reload", timeout=6.0)
        audit("superheroes.roster.reload", "ok", target="superheroes")
        return jsonify({"ok": True, "output": redact(out)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.get("/api/v3/modes/superheroes/diag")
@require_auth
def api_hero_diag():
    """HeroShift has no bespoke diag protocol, so report load state from the
    plugin listing plus the enabled-skill count from skillsInfo.json."""
    active = _superheroes_active()
    # Skill counts come from the file and are always available.
    counts = {"active_count": None, "total": None}
    try:
        skills = read_skills_config()
        rows = [s for s in skills if isinstance(s, dict) and s.get("Name")]
        counts = {"active_count": sum(1 for s in rows if s.get("Active")), "total": len(rows)}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    if not active:
        return jsonify({"ok": True, "loaded": False, "active": False,
                        "diag": counts, "note": "Superheroes is not the active mode"})
    if not rcon_reachable(active["name"]):
        return jsonify({"ok": True, "loaded": False, "active": True,
                        "diag": counts, "note": "RCON not reachable yet"})
    try:
        combined = (rcon_command(active["name"], "css_plugins list", timeout=5.0) + "\n"
                    + rcon_command(active["name"], "meta list", timeout=5.0)).lower()
        loaded = "heroshift" in combined
        counts["raytrace"] = ("raytrace" in combined)
        return jsonify({"ok": True, "loaded": loaded, "active": True, "diag": counts,
                        "note": None if loaded else "HeroShift not loaded"})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


# -------------------------------------------------------------------- console
def load_console_history() -> list:
    return read_json(CONSOLE_HISTORY_JSON, {"items": []}).get("items", [])


@app.post("/api/v3/console/command")
@require_auth
def api_console():
    payload = request.get_json(silent=True) or {}
    command = str(payload.get("command", "")).strip()
    if not command:
        return jsonify({"ok": False, "error": "Command is required"}), 400
    if len(command) > CONSOLE_COMMAND_MAX_LENGTH:
        return jsonify({"ok": False, "error": "Command is too long"}), 400
    if any(ch in command for ch in ("\x00", "\n", "\r")):
        return jsonify({"ok": False, "error": "Invalid characters in command"}), 400

    risk = classify_command(command)
    if risk == "Blocked":
        audit("console.command", "blocked", command)
        return jsonify({"ok": False, "error": f"Command '{command}' is blocked", "risk": risk}), 403

    active = active_container()
    if not active:
        return jsonify({"ok": False, "error": "No game mode is running"}), 409
    if not RCON_PASSWORD:
        return jsonify({"ok": False, "error": "CS2_RCON_PASSWORD is not configured"}), 500

    try:
        output = rcon_command(active["name"], command, timeout=5.0)
        audit("console.command", "ok", command, target=active["mode"])
        # Persist redacted history (never store dangerous secret values verbatim).
        try:
            hist = load_console_history()
            hist.append({"time": now_iso(), "command": redact(command), "risk": risk})
            write_json(CONSOLE_HISTORY_JSON, {"items": hist[-200:]})
        except OSError:
            pass
        return jsonify({"ok": True, "container": active["name"], "command": command,
                        "risk": risk, "output": redact(output)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        audit("console.command", "fail", f"{command}: {exc}", target=active["mode"])
        return jsonify({"ok": False, "error": str(exc), "risk": risk}), 502


@app.get("/api/v3/console/history")
@require_auth
def api_console_history():
    return jsonify({"ok": True, "items": load_console_history()})


# -------------------------------------------------------------------- players
@app.get("/api/v3/players")
@require_auth
def api_players():
    active = active_container()
    if not active:
        return jsonify({"ok": True, "players": [], "active": None})
    if not rcon_reachable(active["name"]):
        return jsonify({"ok": True, "players": [], "active": active["mode"],
                        "note": "RCON not reachable yet"})
    try:
        # Primary source: PanelBridge plugin (includes SteamID64 + team).
        players = None
        source = "plugin"
        try:
            players = parse_panel_players(
                rcon_command(active["name"], "css_panel_players", timeout=5.0))
        except (OSError, RuntimeError, ValueError, PermissionError):
            players = None
        if players is None:
            # Fallback: parse `status` (no SteamID64 on this CS2 build).
            source = "status"
            players = parse_players(rcon_command(active["name"], "status", timeout=5.0))
        return jsonify({"ok": True, "players": players, "active": active["mode"],
                        "source": source})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


def _player_rcon(action: str, steamid: str, command: str):
    active = active_container()
    if not active:
        return jsonify({"ok": False, "error": "No game mode is running"}), 409
    try:
        out = rcon_command(active["name"], command, timeout=5.0)
        audit(f"player.{action}", "ok", f"{command}", target=steamid)
        return jsonify({"ok": True, "output": redact(out)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/v3/players/<ident>/kick")
@require_auth
def api_player_kick(ident):
    userid = (request.get_json(silent=True) or {}).get("userid")
    if userid is None:
        return jsonify({"ok": False, "error": "userid is required to kick"}), 400
    return _player_rcon("kick", ident, f"kickid {int(userid)}")


@app.post("/api/v3/players/<ident>/ban")
@require_auth
def api_player_ban(ident):
    """Ban by userid (Source `banid` resolves the connected player's SteamID).
    minutes=0 is a permanent ban, persisted to banned_user.cfg via writeid."""
    body = request.get_json(silent=True) or {}
    userid = body.get("userid")
    if userid is None:
        return jsonify({"ok": False, "error": "userid is required to ban"}), 400
    try:
        minutes = max(0, int(body.get("minutes", 0)))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "minutes must be a number"}), 400
    active = active_container()
    if not active:
        return jsonify({"ok": False, "error": "No game mode is running"}), 409
    try:
        out = rcon_command(active["name"], f"banid {minutes} {int(userid)}", timeout=5.0)
        if minutes == 0:
            out += "\n" + rcon_command(active["name"], "writeid", timeout=5.0)
        rcon_command(active["name"], f"kickid {int(userid)}", timeout=5.0)
        audit("player.ban", "ok", f"userid={userid} minutes={minutes}", target=ident)
        return jsonify({"ok": True, "output": redact(out)})
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/v3/players/<steamid64>/team")
@require_auth
def api_player_team(steamid64):
    return jsonify({"ok": False, "error": "Team move requires a plugin; available in Phase 2"}), 501


# ------------------------------------------------------------------ password
@app.get("/api/v3/server/password-policy")
@require_auth
def api_password_get():
    sec = load_secrets()
    server = load_server()
    # Never return the actual password.
    return jsonify({"ok": True, "enabled": bool(sec.get("password_enabled")),
                    "has_password": bool(sec.get("server_password")),
                    "policy": server.get("password_policy", "global")})


@app.put("/api/v3/server/password-policy")
@require_auth
def api_password_set():
    payload = request.get_json(silent=True) or {}
    sec = load_secrets()
    action = payload.get("action", "set")

    if action == "generate":
        sec["server_password"] = secrets_mod.token_urlsafe(9)
        sec["password_enabled"] = True
    elif action == "enable":
        sec["password_enabled"] = True
        if payload.get("password"):
            sec["server_password"] = str(payload["password"])
        if not sec.get("server_password"):
            return jsonify({"ok": False, "error": "No password set to enable"}), 400
    elif action == "set":
        if not payload.get("password"):
            return jsonify({"ok": False, "error": "password is required"}), 400
        sec["server_password"] = str(payload["password"])
        sec["password_enabled"] = True
    else:
        return jsonify({"ok": False, "error": "Unknown action"}), 400

    save_secrets(sec)
    _apply_password_live(sec)
    audit("password.update", "ok", f"action={action} enabled={sec['password_enabled']}")
    return jsonify({"ok": True, "enabled": sec["password_enabled"],
                    "has_password": bool(sec.get("server_password"))})


@app.post("/api/v3/server/password/disable")
@require_auth
def api_password_disable():
    sec = load_secrets()
    sec["password_enabled"] = False
    save_secrets(sec)
    _apply_password_live(sec)
    audit("password.disable", "ok")
    return jsonify({"ok": True, "enabled": False})


def _apply_password_live(sec: dict) -> None:
    """Hot-apply the password over RCON and rewrite the active runtime cfg."""
    active = active_container()
    value = sec["server_password"] if sec.get("password_enabled") else ""
    if active and rcon_reachable(active["name"]):
        try:
            rcon_command(active["name"], f'sv_password "{value}"', timeout=5.0)
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            app.logger.warning("password live-apply failed: %s", exc)
        # Rewrite that mode's runtime cfg so it persists across restarts.
        try:
            write_runtime_cfg(active["mode"], load_mode(active["mode"]))
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------- logs
LOG_SOURCES = {
    "game": {"kind": "container", "label": "Game (active)"},
    "docker": {"kind": "container", "label": "Docker / container"},
    "panel": {"kind": "panel", "label": "Panel"},
    "updater": {"kind": "container", "label": "SteamCMD / Updater",
                "container": UPDATER_CONTAINER},
    "audit": {"kind": "audit", "label": "Audit"},
    "plugin": {"kind": "container", "label": "Plugins (filtered)"},
}


@app.get("/api/v3/logs/sources")
@require_auth
def api_log_sources():
    sources = [{"id": k, "label": v["label"]} for k, v in LOG_SOURCES.items()]
    for m, meta in MODES.items():
        sources.append({"id": f"container:{meta['container']}",
                        "label": f"{meta['label']} container"})
    return jsonify({"ok": True, "sources": sources})


@app.get("/api/v3/logs/stream")
@require_auth
def api_logs():
    """Tail logs for a source. (SSE streaming lands with the full log UI; this
    returns a redacted tail suitable for polling.)"""
    source = request.args.get("source", "game").strip()
    try:
        tail = min(max(int(request.args.get("tail", str(LOG_TAIL_DEFAULT))), 20), 2000)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid tail value"}), 400

    if source == "audit":
        try:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            path = AUDIT_DIR / f"audit-{day}.jsonl"
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            return jsonify({"ok": True, "source": "audit",
                            "logs": "\n".join(text.splitlines()[-tail:])})
        except OSError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    if source == "panel":
        try:
            c = client.containers.get(PANEL_CONTAINER)
            out = c.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
            return jsonify({"ok": True, "source": "panel", "logs": redact(out)})
        except (NotFound, DockerException) as exc:
            return jsonify({"ok": True, "source": "panel", "logs": f"(panel logs unavailable: {exc})"})

    # container-backed sources
    if source in ("game", "plugin"):
        active = active_container()
        if not active:
            server = load_server()
            last = server.get("last_mode")
            container = MODES[last]["container"] if last in MODES else None
        else:
            container = active["name"]
    elif source == "docker":
        active = active_container()
        container = active["name"] if active else None
    elif source == "updater":
        container = UPDATER_CONTAINER
    elif source.startswith("container:"):
        container = source.split(":", 1)[1]
        if container not in GAME_CONTAINERS + [UPDATER_CONTAINER, PANEL_CONTAINER]:
            return jsonify({"ok": False, "error": "Unknown container"}), 400
    else:
        return jsonify({"ok": False, "error": "Unknown log source"}), 400

    if not container:
        return jsonify({"ok": True, "source": source, "status": "stopped",
                        "logs": "No active game server."})
    try:
        c = client.containers.get(container)
        c.reload()
        out = c.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        out = redact(out)
        if source == "plugin":
            keep = ("MatchZy", "Metamod", "MM:", "CounterStrikeSharp", "CSSharp",
                    "AutoReady", "RetakesPlugin", "Instadefuse", "GunGame", "GUNGAME",
                    "[CS2 Manager]")
            out = "\n".join(l for l in out.splitlines() if any(k in l for k in keep))
        return jsonify({"ok": True, "source": source, "container": container,
                        "status": c.status, "logs": out})
    except NotFound:
        return jsonify({"ok": True, "source": source, "container": container,
                        "status": "not-created", "logs": "Container not created yet."})
    except DockerException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# --------------------------------------------------------------- maintenance
def _mode_to_restore() -> str | None:
    active = active_container()
    if active:
        return active["mode"]
    last = load_server().get("last_mode")
    return last if last in MODES else None


@app.get("/api/v3/maintenance/jobs")
@require_auth
def api_jobs():
    with JOBS_LOCK:
        jobs = [j.to_dict() for j in sorted(JOBS.values(), key=lambda x: x.start, reverse=True)]
    return jsonify({"ok": True, "jobs": jobs})


@app.get("/api/v3/maintenance/jobs/<job_id>")
@app.get("/api/v3/panel/build-jobs/<job_id>")
@require_auth
def api_job_detail(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Unknown job"}), 404
    return jsonify({"ok": True, "job": job.to_dict(include_log=True)})


@app.post("/api/v3/maintenance/verify-mounts")
@app.get("/api/v3/maintenance/verify-mounts")
@require_auth
def api_verify_mounts():
    checks = verify_mounts()
    ok = all(v is True for v in checks.values() if isinstance(v, bool))
    return jsonify({"ok": True, "all_present": ok, "checks": checks})


@app.post("/api/v3/maintenance/backup")
@require_auth
def api_backup():
    job = start_job("backup", lambda j: j.__setattr__(
        "result", {"path": make_backup(j, "manual").name}))
    return jsonify({"ok": True, "job": job.to_dict()}), 202


@app.post("/api/v3/maintenance/repair-metamod")
@require_auth
def api_repair_metamod():
    restore_mode = _mode_to_restore()

    def worker(job: Job):
        job.set(step="Backup gameinfo + config", percent=15)
        make_backup(job, "pre-repair")
        job.set(step="Stop game service", percent=30)
        with OPERATION_LOCK:
            stop_others(None)
        cancel_pending_rcon()
        job.set(step="Repair Metamod search path", percent=50)
        code = run_updater_container(job, "repair-metamod")
        if code != 0:
            raise RuntimeError(f"Metamod repair failed (exit {code})")
        job.result = {"gameinfo_metamod": gameinfo_has_metamod()}
        if restore_mode:
            job.set(step="Restart previous mode", percent=80)
            if not restart_previous_mode(job, restore_mode):
                job.rollback_status = "restart failed; verify manually"
                raise RuntimeError("Post-repair restart/verify failed")

    return jsonify({"ok": True, "job": start_job("repair-metamod", worker).to_dict()}), 202


def _run_steamcmd_workflow(jtype: str, updater_mode: str):
    """Shared update/validate workflow (Improvment.md section 16.7)."""
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != UPDATER_CONFIRM_PHRASE:
        return jsonify({"ok": False,
                        "error": f'Owner confirmation required: send {{"confirm": "{UPDATER_CONFIRM_PHRASE}"}}'}), 403
    restore_mode = _mode_to_restore()

    def worker(job: Job):
        job.set(step="Pre-flight", percent=5)
        active = active_container()
        if active:
            job.emit(f"Active mode {active['mode']} will be stopped for maintenance.")
        job.set(step="Pre-update backup", percent=15)
        make_backup(job, f"pre-{jtype}")
        job.set(step="Stop game service", percent=25)
        cancel_pending_rcon()
        with OPERATION_LOCK:
            stop_others(None)
        job.set(step=f"SteamCMD {updater_mode} (this is the only SteamCMD run)", percent=35)
        code = run_updater_container(job, updater_mode)
        if code != 0:
            job.rollback_status = "gameinfo .bak retained in install; run rollback.ps1 if needed"
            raise RuntimeError(f"SteamCMD {updater_mode} failed (exit {code})")
        STATE_TIMESTAMPS["last_manual_update"] = now_iso()
        if restore_mode:
            job.set(step="Restart previous mode + verify", percent=80)
            if not restart_previous_mode(job, restore_mode):
                job.rollback_status = "post-update verify failed; investigate before going live"
                raise RuntimeError("Post-update verification failed")
        job.result = {"mode": updater_mode, "restored": restore_mode}

    return jsonify({"ok": True, "job": start_job(jtype, worker).to_dict()}), 202


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
    name = str(body.get("backup", "")).strip()
    if body.get("confirm") != UPDATER_CONFIRM_PHRASE:
        return jsonify({"ok": False,
                        "error": f'Owner confirmation required: send {{"confirm": "{UPDATER_CONFIRM_PHRASE}"}}'}), 403
    # Restrict to a real subdirectory of backups/ (no traversal).
    target = (BACKUPS_DIR / name).resolve()
    if not name or BACKUPS_DIR.resolve() not in target.parents or not target.is_dir():
        return jsonify({"ok": False, "error": "Unknown backup folder"}), 400

    def worker(job: Job):
        job.set(step="Safety backup of current config", percent=10)
        make_backup(job, "pre-restore")
        job.set(step="Stop game service", percent=25)
        with OPERATION_LOCK:
            stop_others(None)
        job.set(step=f"Restore from {name}", percent=45)
        for rel in ("compose.yml", ".env"):
            src = target / rel
            if src.exists():
                shutil.copy2(src, PROJECT_DIR / rel)
                job.emit(f"restored {rel}")
        for rel in ("modes", "data", "shared", "runtime", "updater", "panel"):
            src = target / rel
            if src.is_dir():
                shutil.copytree(src, PROJECT_DIR / rel, dirs_exist_ok=True)
                job.emit(f"restored {rel}/")
        job.result = {"restored_from": name}
        job.emit("Restore complete. Recreate services (start script) to apply mounts/env.")

    return jsonify({"ok": True, "job": start_job("restore", worker).to_dict()}), 202


# ----------------------------------------------------------- panel lifecycle
@app.post("/api/v3/panel/restart")
@require_auth
def api_panel_restart():
    """Restart only the panel container; the game server keeps running."""
    audit("panel.restart", "ok")

    def do_restart():
        time.sleep(1.0)
        try:
            client.containers.get(PANEL_CONTAINER).restart(timeout=10)
        except DockerException:
            pass

    threading.Thread(target=do_restart, daemon=True).start()
    return jsonify({"ok": True, "note": "Panel restarting; reconnect in a few seconds."})


@app.post("/api/v3/panel/rebuild")
@require_auth
def api_panel_rebuild():
    """Build a new panel image, health-check it, then apply via a detached
    applier. Game containers are untouched; the old image is kept for rollback."""
    def worker(job: Job):
        src = PROJECT_DIR / "panel"
        job.set(step="Validate panel source", percent=5)
        if not (src / "app.py").exists():
            raise RuntimeError("panel/app.py not found in project mount")
        # The candidate is health-checked with no modes mount, so validate the
        # live mode manifests here instead: a broken mode.json must fail the
        # rebuild rather than leave the new panel with a half-empty registry.
        _, definition_errors = mode_defs.load_definitions(MODES_ROOT)
        if definition_errors:
            for problem in definition_errors:
                job.emit(f"mode definition: {problem}")
            raise RuntimeError("Mode definitions are invalid; fix mode.json before rebuilding")
        job.emit(f"Mode definitions OK ({', '.join(MODE_DEFS) or 'none'})")

        job.set(step="Build candidate image", percent=20)
        candidate = "cs2-server-panel:candidate"
        _, build_logs = client.images.build(path=str(src), tag=candidate, rm=True, pull=False)
        for entry in build_logs:
            if isinstance(entry, dict) and entry.get("stream"):
                line = entry["stream"].rstrip()
                if line:
                    job.emit(line)

        job.set(step="Health-check candidate", percent=60)
        test_name = f"panel-healthcheck-{job.id}"
        try:
            client.containers.get(test_name).remove(force=True)
        except NotFound:
            pass
        test = client.containers.run(
            candidate, command=["python", "-c", "import app; print('IMPORT_OK')"],
            detach=True, name=test_name, network_mode="none",
            environment={"PANEL_DATA_DIR": "/tmp/d", "PANEL_MODES_DIR": "/tmp/m"})
        out = ""
        try:
            for chunk in test.logs(stream=True, follow=True):
                out += chunk.decode("utf-8", errors="replace")
            code = test.wait().get("StatusCode", -1)
        finally:
            job.emit(out.strip())
            try:
                test.remove(force=True)
            except DockerException:
                pass
        if code != 0 or "IMPORT_OK" not in out:
            job.rollback_status = "candidate discarded; running panel image unchanged"
            raise RuntimeError("Candidate panel image failed health check; not applied")

        job.set(step="Apply (recreate panel)", percent=85)
        client.images.get(candidate).tag("cs2-server-panel", "latest")
        applied = _launch_panel_applier(job)
        job.result = {"applied": applied,
                      "note": "panel will restart" if applied
                      else "build OK; run 'docker compose up -d panel' to apply"}

    return jsonify({"ok": True, "job": start_job("panel-rebuild", worker).to_dict()}), 202


def _launch_panel_applier(job: Job) -> bool:
    """Detached container that recreates the panel with the new image, so the
    swap survives this process being replaced."""
    if not MANAGER_PATH_HOST:
        job.emit("MANAGER_PATH not set; skipping auto-apply.")
        return False
    try:
        client.containers.run(
            "docker:cli",
            command=["sh", "-c",
                     f"sleep 2 && docker compose -p {COMPOSE_PROJECT} "
                     f"-f /work/compose.yml up -d panel"],
            detach=True, remove=True, name=f"panel-applier-{job.id}",
            working_dir="/work",
            volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                     MANAGER_PATH_HOST: {"bind": "/work", "mode": "rw"}})
        job.emit("Applier launched; the panel will recreate momentarily.")
        return True
    except DockerException as exc:
        job.emit(f"Auto-apply unavailable ({exc}). Run 'docker compose up -d panel' to apply.")
        return False


@app.get("/api/v3/audit")
@require_auth
def api_audit():
    try:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = AUDIT_DIR / f"audit-{day}.jsonl"
        items = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return jsonify({"ok": True, "items": items})
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# Seed data + runtime cfgs on import.
ensure_data_files()
