#!/bin/bash
#
# CS2 Manager — Runtime launcher (NO SteamCMD)
# =============================================
# This entrypoint replaces the upstream joedwards32/cs2 entry.sh.
#
# CRITICAL CONTRACT (Improvment.md section 16):
#   - This launcher MUST NEVER invoke SteamCMD.
#   - This launcher MUST NEVER run `app_update`.
#   - This launcher MUST NEVER validate or modify the persistent game install.
#   - It performs read-only health checks, then execs the installed CS2 binary.
#   - Game updates are the exclusive job of the separate `cs2-updater` service.
#
# It faithfully reproduces the config-templating and launch behaviour of the
# upstream entry.sh so existing .env variables keep working, but the entire
# SteamCMD download/validate block is intentionally omitted.

set -euo pipefail

STEAMAPPDIR="${STEAMAPPDIR:-/home/steam/cs2-dedicated}"
CSGO_DIR="${STEAMAPPDIR}/game/csgo"
CS2_BIN="${STEAMAPPDIR}/game/bin/linuxsteamrt64/cs2"
GAMEINFO="${CSGO_DIR}/gameinfo.gi"

log() { echo "[runtime-launcher] $*"; }
fail() { echo "[runtime-launcher][FATAL] $*" >&2; exit 90; }

log "Starting CS2 runtime launcher (SteamCMD is DISABLED in this image)."

# ---------------------------------------------------------------------------
# 1. Read-only health checks. Fail clearly if the persistent install is missing.
#    We NEVER attempt to download or repair here.
# ---------------------------------------------------------------------------
if [[ ! -d "${STEAMAPPDIR}/game" ]]; then
    fail "Game install not found at ${STEAMAPPDIR}/game. Run the cs2-updater maintenance job to install CS2. Runtime images never download the game."
fi
if [[ ! -f "${CS2_BIN}" ]]; then
    fail "CS2 binary missing at ${CS2_BIN}. The persistent install looks incomplete; run the cs2-updater maintenance job."
fi

# Metamod search-path check is advisory only. Repair is a controlled maintenance
# action (panel /maintenance/repair-metamod), never something we do mid-launch.
if [[ -f "${GAMEINFO}" ]]; then
    if grep -q "csgo/addons/metamod" "${GAMEINFO}"; then
        log "gameinfo.gi Metamod search path: OK"
    else
        log "WARNING: gameinfo.gi is missing the 'Game csgo/addons/metamod' search path. Plugins will NOT load. Use the panel Metamod repair action."
    fi
else
    log "WARNING: gameinfo.gi not found at ${GAMEINFO}."
fi

# ---------------------------------------------------------------------------
# 2. steamclient.so symlink fix (local symlink only, no network access).
# ---------------------------------------------------------------------------
STEAMCMDDIR="${STEAMCMDDIR:-/home/steam/steamcmd}"
if [[ -f "${STEAMCMDDIR}/linux64/steamclient.so" ]]; then
    mkdir -p ~/.steam/sdk64
    ln -sfT "${STEAMCMDDIR}/linux64/steamclient.so" ~/.steam/sdk64/steamclient.so || true
fi

# ---------------------------------------------------------------------------
# 3. server.cfg install + templating (mirrors upstream entry.sh, no downloads).
# ---------------------------------------------------------------------------
mkdir -p "${CSGO_DIR}/cfg"
if [[ -f /etc/server.cfg ]]; then
    cp /etc/server.cfg "${CSGO_DIR}/cfg/server.cfg"
fi

if [[ -f "${CSGO_DIR}/cfg/server.cfg" ]]; then
    sed -i -e "s/{{SERVER_HOSTNAME}}/${CS2_SERVERNAME:-CS2 Server}/g" \
           -e "s/{{SERVER_CHEATS}}/${CS2_CHEATS:-0}/g" \
           -e "s/{{SERVER_HIBERNATE}}/${CS2_SERVER_HIBERNATE:-0}/g" \
           -e "s/{{SERVER_PW}}/${CS2_PW:-}/g" \
           -e "s/{{SERVER_RCON_PW}}/${CS2_RCONPW:-}/g" \
           -e "s/{{TV_ENABLE}}/${TV_ENABLE:-0}/g" \
           -e "s/{{TV_PORT}}/${TV_PORT:-27020}/g" \
           -e "s/{{TV_AUTORECORD}}/${TV_AUTORECORD:-0}/g" \
           -e "s/{{TV_PW}}/${TV_PW:-}/g" \
           -e "s/{{TV_RELAY_PW}}/${TV_RELAY_PW:-}/g" \
           -e "s/{{TV_MAXRATE}}/${TV_MAXRATE:-0}/g" \
           -e "s/{{TV_DELAY}}/${TV_DELAY:-0}/g" \
           -e "s/{{SERVER_LOG}}/${CS2_LOG:-on}/g" \
           -e "s/{{SERVER_LOG_FILE}}/${CS2_LOG_FILE:-0}/g" \
           -e "s/{{SERVER_LOG_ECHO}}/${CS2_LOG_ECHO:-1}/g" \
           -e "s/{{SERVER_LOG_MONEY}}/${CS2_LOG_MONEY:-0}/g" \
           -e "s/{{SERVER_LOG_DETAIL}}/${CS2_LOG_DETAIL:-0}/g" \
           -e "s/{{SERVER_LOG_ITEMS}}/${CS2_LOG_ITEMS:-0}/g" \
           -e "s/{{SERVER_DISCONNECT_KILLS}}/${CS2_DISCONNECT_KILLS:-0}/g" \
           "${CSGO_DIR}/cfg/server.cfg" || true

    if [[ -n "${CS2_LOG_HTTP_URL:-}" ]]; then
        printf 'logaddress_add_http "%s"\n' "${CS2_LOG_HTTP_URL}" >> "${CSGO_DIR}/cfg/server.cfg"
    fi
fi

if [[ -n "${CS2_BOT_DIFFICULTY:-}" ]]; then
    sed -i "s/bot_difficulty.*/bot_difficulty ${CS2_BOT_DIFFICULTY}/" "${CSGO_DIR}"/cfg/* 2>/dev/null || true
fi
if [[ -n "${CS2_BOT_QUOTA:-}" ]]; then
    sed -ri "s/bot_quota[[:space:]]+.*/bot_quota ${CS2_BOT_QUOTA}/" "${CSGO_DIR}"/cfg/* 2>/dev/null || true
fi
if [[ -n "${CS2_BOT_QUOTA_MODE:-}" ]]; then
    sed -i "s/bot_quota_mode.*/bot_quota_mode ${CS2_BOT_QUOTA_MODE}/" "${CSGO_DIR}"/cfg/* 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 4. Launch. Build arguments as arrays so each +exec profile command reaches
#    CS2 as a separate argument. Avoid eval: it can collapse or reinterpret the
#    profile string and previously made missing profile mounts hard to diagnose.
# ---------------------------------------------------------------------------
cd "${STEAMAPPDIR}/game/"

# Optional hooks, only if present in the persistent install.
if [[ -f "${STEAMAPPDIR}/pre.sh" ]]; then
    # shellcheck disable=SC1090
    source "${STEAMAPPDIR}/pre.sh" || true
fi

GAME_MODE_ARGS=()
if [[ -z "${CS2_GAMEALIAS:-}" ]]; then
    GAME_MODE_ARGS=(+game_type "${CS2_GAMETYPE:-0}" +game_mode "${CS2_GAMEMODE:-0}")
else
    GAME_MODE_ARGS=(+game_alias "${CS2_GAMEALIAS}")
fi

IP_ARGS=()
[[ -n "${CS2_IP:-}" ]] && IP_ARGS=(-ip "${CS2_IP}")

STEAM_ACCOUNT_ARGS=()
[[ -n "${SRCDS_TOKEN:-}" ]] && STEAM_ACCOUNT_ARGS=(+sv_setsteamaccount "${SRCDS_TOKEN}")

PASSWORD_ARGS=()
[[ -n "${CS2_PW:-}" ]] && PASSWORD_ARGS=(+sv_password "${CS2_PW}")

ADDITIONAL_ARGS=()
if [[ -n "${CS2_ADDITIONAL_ARGS:-}" ]]; then
    read -r -a ADDITIONAL_ARGS <<< "${CS2_ADDITIONAL_ARGS}"
fi

# Validate every profile/config referenced by +exec before starting CS2. Bind
# mount mistakes now fail with the exact missing path instead of silently
# starting the default game mode.
for ((i = 0; i < ${#ADDITIONAL_ARGS[@]}; i++)); do
    if [[ "${ADDITIONAL_ARGS[$i]}" == "+exec" ]]; then
        ((i + 1 < ${#ADDITIONAL_ARGS[@]})) || fail "CS2_ADDITIONAL_ARGS ends with +exec but no cfg filename"
        cfg_name="${ADDITIONAL_ARGS[$((i + 1))]}"
        cfg_path="${CSGO_DIR}/cfg/${cfg_name}"
        [[ -f "${cfg_path}" ]] || fail "Profile cfg is not mounted: ${cfg_path}"
        log "Profile cfg available: ${cfg_name}"
        ((i += 1))
    fi
done

# RCON proxy (upstream uses simpleproxy for a separate rcon port). Only if requested.
if [[ -n "${CS2_RCON_PORT:-}" ]] && command -v simpleproxy >/dev/null 2>&1; then
    log "Establishing simpleproxy for ${CS2_RCON_PORT} -> 127.0.0.1:${CS2_PORT:-27015}"
    simpleproxy -L "${CS2_RCON_PORT}" -R 127.0.0.1:"${CS2_PORT:-27015}" &
fi

log "Launching CS2 dedicated server (game_alias=${CS2_GAMEALIAS:-<type/mode>}, map=${CS2_STARTMAP:-de_dust2}, maxplayers=${CS2_MAXPLAYERS:-10})"
log "Additional launch args: ${ADDITIONAL_ARGS[*]:-<none>}"

exec ./cs2.sh -dedicated \
    "${IP_ARGS[@]}" \
    -port "${CS2_PORT:-27015}" \
    -console \
    -usercon \
    -maxplayers "${CS2_MAXPLAYERS:-10}" \
    "${GAME_MODE_ARGS[@]}" \
    +mapgroup "${CS2_MAPGROUP:-mg_active}" \
    +map "${CS2_STARTMAP:-de_dust2}" \
    +rcon_password "${CS2_RCONPW:-}" \
    "${STEAM_ACCOUNT_ARGS[@]}" \
    "${PASSWORD_ARGS[@]}" \
    +sv_lan "${CS2_LAN:-0}" \
    +tv_port "${TV_PORT:-27020}" \
    "${ADDITIONAL_ARGS[@]}"
