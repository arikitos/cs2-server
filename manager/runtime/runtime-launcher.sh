#!/usr/bin/env bash
# Starts the single CS2 runtime. It never invokes SteamCMD.
# Before launch it transactionally deploys only files declared by the active
# mode and removes only files recorded in the previous managed inventory.
set -euo pipefail

STEAMAPPDIR="${STEAMAPPDIR:-/home/steam/cs2-dedicated}"
CSGO_DIR="${STEAMAPPDIR}/game/csgo"
CS2_BIN="${STEAMAPPDIR}/game/bin/linuxsteamrt64/cs2"
GAMEINFO="${CSGO_DIR}/gameinfo.gi"
MODE_STATE_PATH="${MODE_STATE_PATH:-/manager/data/runtime/active-mode.json}"
MODE_INVENTORY_PATH="${MODE_INVENTORY_PATH:-${STEAMAPPDIR}/.cs2-manager/managed-files.json}"
MODE_VERSIONS_PATH="${MODE_VERSIONS_PATH:-/manager/versions.json}"
MODE_ENV="/tmp/cs2-mode.env"

log() { echo "[runtime-launcher] $*"; }
fail() { echo "[runtime-launcher][FATAL] $*" >&2; exit 90; }

log "Starting single CS2 runtime (SteamCMD is disabled)."
[[ -d "${STEAMAPPDIR}/game" ]] || fail "Game install missing at ${STEAMAPPDIR}/game"
[[ -f "${CS2_BIN}" ]] || fail "CS2 binary missing at ${CS2_BIN}; run the updater maintenance job"
[[ -f "${MODE_STATE_PATH}" ]] || fail "Active mode state missing at ${MODE_STATE_PATH}; select a mode in the panel"

if [[ -f "${GAMEINFO}" ]] && grep -q "csgo/addons/metamod" "${GAMEINFO}"; then
    log "gameinfo.gi Metamod search path: OK"
else
    log "WARNING: Metamod search path is missing; use the controlled repair action"
fi

log "Deploying active mode transactionally."
/usr/local/bin/mode-applier \
    --modes-root /manager/modes \
    --shared-root /manager/shared \
    --server-root "${STEAMAPPDIR}" \
    --inventory "${MODE_INVENTORY_PATH}" \
    --versions "${MODE_VERSIONS_PATH}" \
    --installed-versions "${CSGO_DIR}/addons/.cs2-manager-versions.json" \
    apply --state "${MODE_STATE_PATH}" --env "${MODE_ENV}"

# The applier validates every value before writing this simple KEY=value file.
# shellcheck disable=SC1090
source "${MODE_ENV}"
export CS2_ACTIVE_MODE CS2_GAMEALIAS CS2_MAXPLAYERS CS2_STARTMAP CS2_MODE_CFG CS2_RUNTIME_CFG
log "Mode deployed: ${CS2_ACTIVE_MODE}"

STEAMCMDDIR="${STEAMCMDDIR:-/home/steam/steamcmd}"
if [[ -f "${STEAMCMDDIR}/linux64/steamclient.so" ]]; then
    mkdir -p ~/.steam/sdk64
    ln -sfT "${STEAMCMDDIR}/linux64/steamclient.so" ~/.steam/sdk64/steamclient.so || true
fi

# The shared server.cfg is part of the deployed mode inventory. Template it only
# after deployment so every launch starts from the repository source version.
# Python string replacement avoids sed delimiter/replacement injection from
# operator-provided values such as the server name or passwords.
if [[ -f "${CSGO_DIR}/cfg/server.cfg" ]]; then
    python3 - "${CSGO_DIR}/cfg/server.cfg" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
values = {
    "SERVER_HOSTNAME": os.environ.get("CS2_SERVERNAME", "CS2 Server"),
    "SERVER_CHEATS": os.environ.get("CS2_CHEATS", "0"),
    "SERVER_HIBERNATE": os.environ.get("CS2_SERVER_HIBERNATE", "0"),
    "SERVER_PW": os.environ.get("CS2_PW", ""),
    "SERVER_RCON_PW": os.environ.get("CS2_RCONPW", ""),
    "TV_ENABLE": os.environ.get("TV_ENABLE", "0"),
    "TV_PORT": os.environ.get("TV_PORT", "27020"),
    "TV_AUTORECORD": os.environ.get("TV_AUTORECORD", "0"),
    "TV_PW": os.environ.get("TV_PW", ""),
    "TV_RELAY_PW": os.environ.get("TV_RELAY_PW", ""),
    "TV_MAXRATE": os.environ.get("TV_MAXRATE", "0"),
    "TV_DELAY": os.environ.get("TV_DELAY", "0"),
    "SERVER_LOG": os.environ.get("CS2_LOG", "on"),
    "SERVER_LOG_FILE": os.environ.get("CS2_LOG_FILE", "0"),
    "SERVER_LOG_ECHO": os.environ.get("CS2_LOG_ECHO", "1"),
    "SERVER_LOG_MONEY": os.environ.get("CS2_LOG_MONEY", "0"),
    "SERVER_LOG_DETAIL": os.environ.get("CS2_LOG_DETAIL", "0"),
    "SERVER_LOG_ITEMS": os.environ.get("CS2_LOG_ITEMS", "0"),
    "SERVER_DISCONNECT_KILLS": os.environ.get("CS2_SERVER_DISCONNECT_KILLS", "0"),
}
for key, value in values.items():
    text = text.replace("{{" + key + "}}", value)
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(text, encoding="utf-8", newline="\n")
tmp.replace(path)
PY
fi

for cfg_name in "${CS2_MODE_CFG}" "${CS2_RUNTIME_CFG}"; do
    [[ -f "${CSGO_DIR}/cfg/${cfg_name}" ]] || fail "Deployed cfg missing: ${cfg_name}"
done

cd "${STEAMAPPDIR}/game/"
[[ -f "${STEAMAPPDIR}/pre.sh" ]] && source "${STEAMAPPDIR}/pre.sh" || true

IP_ARGS=()
[[ -n "${CS2_IP:-}" ]] && IP_ARGS=(-ip "${CS2_IP}")
STEAM_ACCOUNT_ARGS=()
[[ -n "${SRCDS_TOKEN:-}" ]] && STEAM_ACCOUNT_ARGS=(+sv_setsteamaccount "${SRCDS_TOKEN}")
PASSWORD_ARGS=()
[[ -n "${CS2_PW:-}" ]] && PASSWORD_ARGS=(+sv_password "${CS2_PW}")

log "Launching mode=${CS2_ACTIVE_MODE}, alias=${CS2_GAMEALIAS}, map=${CS2_STARTMAP}, maxplayers=${CS2_MAXPLAYERS}"
exec ./cs2.sh -dedicated \
    "${IP_ARGS[@]}" \
    -port "${CS2_PORT:-27015}" \
    -console \
    -usercon \
    -maxplayers "${CS2_MAXPLAYERS}" \
    +game_alias "${CS2_GAMEALIAS}" \
    +mapgroup "${CS2_MAPGROUP:-mg_active}" \
    +map "${CS2_STARTMAP}" \
    +rcon_password "${CS2_RCONPW:-}" \
    "${STEAM_ACCOUNT_ARGS[@]}" \
    "${PASSWORD_ARGS[@]}" \
    +sv_lan "${CS2_LAN:-0}" \
    +tv_port "${TV_PORT:-27020}" \
    +exec "${CS2_MODE_CFG}" \
    +exec "${CS2_RUNTIME_CFG}"
