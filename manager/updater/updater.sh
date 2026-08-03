#!/bin/bash
#
# CS2 Manager — Maintenance updater (the ONLY place SteamCMD runs)
# ================================================================
# Improvment.md section 16.3 / 16.7. This service:
#   - Is stopped by default and has no published game ports.
#   - Runs only from an explicit Owner action (panel) or manual `docker compose run`.
#   - Requires a confirmation phrase (CS2_UPDATER_CONFIRM).
#   - Runs SteamCMD app_update against the persistent install.
#   - Repairs and verifies the Metamod search path in gameinfo.gi.
#   - Verifies CounterStrikeSharp + Metamod files.
#   - Exits non-zero on failure so the panel can roll back.
#
# Backups (pre-update) and restarting the previously active mode are orchestrated
# by the panel, NOT here, so this container stays single-purpose.

set -uo pipefail

STEAMAPPID="${STEAMAPPID:-730}"
STEAMAPPDIR="${STEAMAPPDIR:-/home/steam/cs2-dedicated}"
STEAMCMDDIR="${STEAMCMDDIR:-/home/steam/steamcmd}"
STEAM_PLATFORM="${STEAM_PLATFORM:-linux}"
CSGO_DIR="${STEAMAPPDIR}/game/csgo"
GAMEINFO="${CSGO_DIR}/gameinfo.gi"
# Exactly matches the surrounding SearchPaths indentation: 3 tabs, Game, tab, path.
METAMOD_LINE="$(printf '\t\t\tGame\tcsgo/addons/metamod')"
CONFIRM_PHRASE="UPDATE CS2"

log()  { echo "[updater] $*"; }
warn() { echo "[updater][WARN] $*" >&2; }
fail() { echo "[updater][FATAL] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. Safety gate — refuse to run without the explicit confirmation phrase.
# ---------------------------------------------------------------------------
MODE="${CS2_UPDATER_MODE:-update}"   # update | validate | repair-metamod
if [[ "${CS2_UPDATER_CONFIRM:-}" != "${CONFIRM_PHRASE}" ]]; then
    fail "Refusing to run. Set CS2_UPDATER_CONFIRM=\"${CONFIRM_PHRASE}\" to proceed. (mode=${MODE})"
fi
log "Confirmation accepted. Maintenance mode: ${MODE}"

# ---------------------------------------------------------------------------
# 1. Metamod repair helper (used by update and repair-metamod modes).
# ---------------------------------------------------------------------------
repair_metamod() {
    [[ -f "${GAMEINFO}" ]] || { warn "gameinfo.gi not found at ${GAMEINFO}, cannot repair."; return 1; }
    if grep -q "csgo/addons/metamod" "${GAMEINFO}"; then
        log "Metamod search path already present in gameinfo.gi."
        return 0
    fi
    log "Metamod search path missing. Repairing gameinfo.gi ..."
    cp -a "${GAMEINFO}" "${GAMEINFO}.bak.$(date +%s)"
    # Insert the Metamod Game line immediately after the SearchPaths opening brace.
    awk -v line="${METAMOD_LINE}" '
        BEGIN { done=0 }
        /Game_LowViolence/ && done==0 { print line; done=1 }
        { print }
    ' "${GAMEINFO}" > "${GAMEINFO}.tmp"
    if grep -q "csgo/addons/metamod" "${GAMEINFO}.tmp"; then
        mv "${GAMEINFO}.tmp" "${GAMEINFO}"
        log "Metamod search path inserted."
        return 0
    fi
    rm -f "${GAMEINFO}.tmp"
    warn "Automatic Metamod insertion point not found; manual repair required."
    return 1
}

# ---------------------------------------------------------------------------
# 2. Fresh-install (bootstrap) detection.
#
# SteamCMD delivers ONLY the base game. Metamod and CounterStrikeSharp are
# installed separately (manager/scripts/install-mods-linux.sh), so on a fresh
# bootstrap into an empty CS2_DATA_PATH the addon checks below cannot pass yet
# and a successful download would otherwise be reported as a failed update.
#
# Detection runs BEFORE SteamCMD. On an existing install the addons are already
# present at that point, so they stay strictly REQUIRED and a genuine regression
# (addons wiped by an update) still fails the job as before.
# ---------------------------------------------------------------------------
FRESH_INSTALL=0

detect_fresh_install() {
    if [[ ! -f "${STEAMAPPDIR}/game/bin/linuxsteamrt64/cs2" ]] \
    && [[ ! -d "${CSGO_DIR}/addons/metamod" ]] \
    && [[ ! -d "${CSGO_DIR}/addons/counterstrikesharp" ]]; then
        FRESH_INSTALL=1
        log "No CS2 binary and no addons found: treating this as a FRESH bootstrap install."
        log "This job installs the base game only. Metamod / CounterStrikeSharp come next:"
        log "  docker compose --profile maintenance run --rm cs2-modinstaller"
        log "  CS2_UPDATER_MODE=repair-metamod CS2_UPDATER_CONFIRM=\"${CONFIRM_PHRASE}\" docker compose --profile maintenance run --rm cs2-updater"
    fi
}

# ---------------------------------------------------------------------------
# 3. Verification helper.
# ---------------------------------------------------------------------------
verify_install() {
    local ok=0
    local linux_binary="${STEAMAPPDIR}/game/bin/linuxsteamrt64/cs2"
    local windows_binary="${STEAMAPPDIR}/game/bin/win64/cs2.exe"

    # The Linux game binary is required unconditionally, bootstrap or not.
    if [[ ! -f "${linux_binary}" ]]; then
        if [[ -f "${windows_binary}" ]]; then
            warn "Windows CS2 files detected at ${windows_binary}, but the Docker runtime requires the Linux depot."
        else
            warn "Linux CS2 binary missing at ${linux_binary}"
        fi
        ok=1
    fi

    # Addon checks: required on an existing install, advisory during bootstrap.
    local addons_ok=0
    [[ -d "${CSGO_DIR}/addons/metamod" ]] || { warn "Metamod addon dir missing"; addons_ok=1; }
    [[ -d "${CSGO_DIR}/addons/counterstrikesharp" ]] || { warn "CounterStrikeSharp addon dir missing"; addons_ok=1; }
    grep -q "csgo/addons/metamod" "${GAMEINFO}" 2>/dev/null || { warn "gameinfo.gi missing Metamod search path"; addons_ok=1; }
    if [[ $addons_ok != 0 ]]; then
        if [[ $FRESH_INSTALL == 1 ]]; then
            log "Addon warnings above are expected on a fresh bootstrap and are NOT treated as failures."
            log "Run cs2-modinstaller, then cs2-updater in repair-metamod mode, before starting a mode."
        else
            ok=1
        fi
    fi
    return $ok
}

case "${MODE}" in
    repair-metamod)
        repair_metamod || fail "Metamod repair failed."
        verify_install || fail "Post-repair verification failed."
        log "Metamod repair complete."
        exit 0
        ;;
    update|validate)
        detect_fresh_install
        VALIDATE=""
        [[ "${MODE}" == "validate" ]] && VALIDATE="validate"
        log "Running SteamCMD app_update ${STEAMAPPID} ${VALIDATE} for platform ${STEAM_PLATFORM} ..."
        steamcmd_rc=1
        attempt=0
        while [[ $steamcmd_rc != 0 ]] && [[ $attempt -lt 3 ]]; do
            ((attempt+=1))
            [[ $attempt -gt 1 ]] && log "Retrying SteamCMD (attempt ${attempt}) ..."
            bash "${STEAMCMDDIR}/steamcmd.sh" \
                +force_install_dir "${STEAMAPPDIR}" \
                +@sSteamCmdForcePlatformType "${STEAM_PLATFORM}" \
                +@bClientTryRequestManifestWithoutCode 1 \
                +login anonymous \
                +app_update "${STEAMAPPID}" ${VALIDATE} \
                +quit
            steamcmd_rc=$?
        done
        [[ $steamcmd_rc == 0 ]] || fail "SteamCMD failed with code ${steamcmd_rc}."
        log "SteamCMD update finished. Repairing Metamod search path ..."
        repair_metamod || warn "Metamod repair reported an issue; verification will decide."
        verify_install || fail "Post-update verification failed. Panel should roll back."
        log "Update + verification complete. Restart of the previous mode is handled by the panel."
        exit 0
        ;;
    *)
        fail "Unknown CS2_UPDATER_MODE=${MODE} (expected update | validate | repair-metamod)."
        ;;
esac
