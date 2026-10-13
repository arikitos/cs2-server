#!/bin/bash
#
# CS2 Manager, Maintenance updater
# ================================
# SteamCMD runs only in this maintenance image. The panel owns backup creation,
# stopping the game process, and restarting the previously selected mode.

set -uo pipefail

STEAMAPPID="${STEAMAPPID:-730}"
STEAMAPPDIR="${STEAMAPPDIR:-/home/steam/cs2-dedicated}"
STEAMCMDDIR="${STEAMCMDDIR:-/home/steam/steamcmd}"
STEAM_PLATFORM="${STEAM_PLATFORM:-linux}"
CSGO_DIR="${STEAMAPPDIR}/game/csgo"
GAMEINFO="${CSGO_DIR}/gameinfo.gi"
METAMOD_LINE="$(printf '\t\t\tGame\tcsgo/addons/metamod')"
CONFIRM_PHRASE="UPDATE CS2"

log()  { echo "[updater] $*"; }
warn() { echo "[updater][WARN] $*" >&2; }
fail() { echo "[updater][FATAL] $*" >&2; exit 1; }

MODE="${CS2_UPDATER_MODE:-update}"
if [[ "${CS2_UPDATER_CONFIRM:-}" != "${CONFIRM_PHRASE}" ]]; then
    fail "Refusing to run. Set CS2_UPDATER_CONFIRM=\"${CONFIRM_PHRASE}\" to proceed. (mode=${MODE})"
fi
log "Confirmation accepted. Maintenance mode: ${MODE}"

metamod_search_path_present() {
    local target="${1:-${GAMEINFO}}"
    [[ -f "${target}" ]] || return 1

    awk '
        BEGIN { waiting=0; in_paths=0; found=0 }
        {
            line=$0
            sub(/[[:space:]]*\/\/.*/, "", line)

            if (!in_paths && line ~ /^[[:space:]]*SearchPaths[[:space:]]*\{?[[:space:]]*$/) {
                if (line ~ /\{/) {
                    in_paths=1
                } else {
                    waiting=1
                }
                next
            }

            if (waiting) {
                if (line ~ /^[[:space:]]*\{[[:space:]]*$/) {
                    in_paths=1
                    waiting=0
                }
                next
            }

            if (in_paths && line ~ /^[[:space:]]*\}/) {
                exit
            }

            if (in_paths && line ~ /^[[:space:]]*Game[[:space:]]+csgo\/addons\/metamod[[:space:]]*$/) {
                found=1
                exit
            }
        }
        END { exit found ? 0 : 1 }
    ' "${target}"
}

insert_metamod_search_path() {
    local source="$1"
    local target="$2"

    awk -v metamod_line="${METAMOD_LINE}" '
        BEGIN { waiting=0; done=0 }
        {
            clean=$0
            sub(/[[:space:]]*\/\/.*/, "", clean)

            if (!done && !waiting && clean ~ /^[[:space:]]*SearchPaths[[:space:]]*\{?[[:space:]]*$/) {
                print
                if (clean ~ /\{/) {
                    print metamod_line
                    done=1
                } else {
                    waiting=1
                }
                next
            }

            if (waiting) {
                print
                if (clean ~ /^[[:space:]]*\{[[:space:]]*$/) {
                    print metamod_line
                    done=1
                    waiting=0
                }
                next
            }

            print
        }
        END { if (!done) exit 42 }
    ' "${source}" > "${target}"
}

repair_metamod() {
    [[ -f "${GAMEINFO}" ]] || { warn "gameinfo.gi not found at ${GAMEINFO}, cannot repair."; return 1; }

    if metamod_search_path_present "${GAMEINFO}"; then
        log "Metamod search path is already active inside SearchPaths."
        return 0
    fi

    log "Metamod search path is missing from SearchPaths. Repairing gameinfo.gi ..."
    cp -a "${GAMEINFO}" "${GAMEINFO}.bak.$(date +%s)"

    if ! insert_metamod_search_path "${GAMEINFO}" "${GAMEINFO}.tmp"; then
        rm -f "${GAMEINFO}.tmp"
        warn "The SearchPaths block could not be located. Manual repair is required."
        return 1
    fi

    if ! metamod_search_path_present "${GAMEINFO}.tmp"; then
        rm -f "${GAMEINFO}.tmp"
        warn "The generated gameinfo.gi did not contain a valid active Metamod path."
        return 1
    fi

    mv "${GAMEINFO}.tmp" "${GAMEINFO}"
    log "Metamod search path inserted inside SearchPaths."
}

FRESH_INSTALL=0

detect_fresh_install() {
    if [[ ! -f "${STEAMAPPDIR}/game/bin/linuxsteamrt64/cs2" ]] \
    && [[ ! -d "${CSGO_DIR}/addons/metamod" ]] \
    && [[ ! -d "${CSGO_DIR}/addons/counterstrikesharp" ]]; then
        FRESH_INSTALL=1
        log "No CS2 binary and no addons found. Treating this as a fresh bootstrap install."
        log "This job installs the base game only. Install the addons afterwards with:"
        log "  docker compose --profile maintenance run --rm cs2-modinstaller"
        log "  CS2_UPDATER_MODE=repair-metamod CS2_UPDATER_CONFIRM=\"${CONFIRM_PHRASE}\" docker compose --profile maintenance run --rm cs2-updater"
    fi
}

verify_install() {
    local ok=0
    local linux_binary="${STEAMAPPDIR}/game/bin/linuxsteamrt64/cs2"
    local windows_binary="${STEAMAPPDIR}/game/bin/win64/cs2.exe"

    if [[ ! -f "${linux_binary}" ]]; then
        if [[ -f "${windows_binary}" ]]; then
            warn "Windows CS2 files detected at ${windows_binary}, but the Docker runtime requires the Linux depot."
        else
            warn "Linux CS2 binary missing at ${linux_binary}"
        fi
        ok=1
    fi

    local addons_ok=0
    [[ -d "${CSGO_DIR}/addons/metamod" ]] || { warn "Metamod addon directory missing"; addons_ok=1; }
    [[ -d "${CSGO_DIR}/addons/counterstrikesharp" ]] || { warn "CounterStrikeSharp addon directory missing"; addons_ok=1; }
    metamod_search_path_present "${GAMEINFO}" || { warn "gameinfo.gi has no active Metamod entry inside SearchPaths"; addons_ok=1; }

    if [[ ${addons_ok} != 0 ]]; then
        if [[ ${FRESH_INSTALL} == 1 ]]; then
            log "Addon warnings are expected during a fresh bootstrap and are not treated as failures."
            log "Run cs2-modinstaller, then run cs2-updater in repair-metamod mode before starting a game mode."
        else
            ok=1
        fi
    fi

    return ${ok}
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

        steamcmd_args=(
            +force_install_dir "${STEAMAPPDIR}"
            +@sSteamCmdForcePlatformType "${STEAM_PLATFORM}"
            +@bClientTryRequestManifestWithoutCode 1
            +login anonymous
            +app_update "${STEAMAPPID}"
        )
        if [[ "${MODE}" == "validate" ]]; then
            steamcmd_args+=(validate)
        fi
        steamcmd_args+=(+quit)

        log "Running SteamCMD app_update ${STEAMAPPID} in ${MODE} mode for platform ${STEAM_PLATFORM} ..."
        steamcmd_rc=1
        attempt=0
        while [[ ${steamcmd_rc} != 0 ]] && [[ ${attempt} -lt 3 ]]; do
            ((attempt+=1))
            [[ ${attempt} -gt 1 ]] && log "Retrying SteamCMD, attempt ${attempt} ..."
            bash "${STEAMCMDDIR}/steamcmd.sh" "${steamcmd_args[@]}"
            steamcmd_rc=$?
        done

        [[ ${steamcmd_rc} == 0 ]] || fail "SteamCMD failed with code ${steamcmd_rc}."
        log "SteamCMD finished. Repairing the Metamod search path ..."
        repair_metamod || warn "Metamod repair reported an issue. Verification will decide the result."
        verify_install || fail "Post-update verification failed. The server remains stopped for operator recovery."
        log "Update and verification complete. The panel handles restart of the previous mode."
        exit 0
        ;;
    *)
        fail "Unknown CS2_UPDATER_MODE=${MODE}. Expected update, validate, or repair-metamod."
        ;;
esac
