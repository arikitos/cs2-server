#!/usr/bin/env bash
#
# Installs Metamod:Source + CounterStrikeSharp into the persistent CS2 install.
# Required after a fresh bootstrap, because cs2-updater (SteamCMD) delivers only
# the base game.
#
# Runs either inside the maintenance container (`docker compose --profile
# maintenance run --rm cs2-modinstaller`, where CS2_DATA_DIR already points at
# the mounted install) or directly on a Linux / WSL / Git Bash host.
#
# The retake / faceit mode plugin folders are pinned in git, so they are left
# alone unless --with-mode-plugins is passed.
set -euo pipefail

MANAGER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(cd "${MANAGER_DIR}/.." && pwd)"

WITH_MODE_PLUGINS=0
for arg in "$@"; do
  case "$arg" in
    # --with-profiles is the pre-rename name, still accepted.
    --with-mode-plugins|--with-profiles) WITH_MODE_PLUGINS=1 ;;
    *) echo "Unknown argument: $arg (expected --with-mode-plugins)" >&2; exit 2 ;;
  esac
done

# Install location. CS2_DATA_DIR wins so the container run needs no .env; the
# direct-host path falls back to CS2_DATA_PATH from the project-root .env.
if [[ -z "${CS2_DATA_DIR:-}" ]]; then
  if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
    echo "Missing ${PROJECT_DIR}/.env. Copy .env.example to .env, or set CS2_DATA_DIR." >&2
    exit 1
  fi
  set -a; source "${PROJECT_DIR}/.env"; set +a
  [[ -n "${CS2_DATA_PATH:-}" ]] || { echo "CS2_DATA_PATH is not set in ${PROJECT_DIR}/.env." >&2; exit 1; }
  CS2_DATA_DIR="${CS2_DATA_PATH}"
  # Translate a Windows CS2_DATA_PATH (C:/foo) for WSL (/mnt/c/foo) or Git Bash (/c/foo).
  if [[ "${CS2_DATA_DIR}" =~ ^([A-Za-z]):[/\\](.*)$ ]]; then
    drive="$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:upper:]' '[:lower:]')"
    rest="${BASH_REMATCH[2]//\\//}"
    if [[ -d "/mnt/${drive}" ]]; then
      CS2_DATA_DIR="/mnt/${drive}/${rest}"
    else
      CS2_DATA_DIR="/${drive}/${rest}"
    fi
  fi
fi

DATA="$(cd "${PROJECT_DIR}" && realpath -m "${CS2_DATA_DIR}")"
CSGO="$DATA/game/csgo"

# Never seed addons into an empty tree: that would leave a half-install that the
# updater then mistakes for an existing one.
if [[ ! -f "$DATA/game/bin/linuxsteamrt64/cs2" ]]; then
  echo "CS2 is not installed at $DATA (game/bin/linuxsteamrt64/cs2 missing)." >&2
  echo "Run the cs2-updater maintenance job first, then re-run this script." >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$CSGO"

latest_asset_url() {
  local repo="$1" regex="$2"
  curl -fsSL "https://api.github.com/repos/$repo/releases/latest" \
    | python3 -c 'import json,sys,re; d=json.load(sys.stdin); p=re.compile(sys.argv[1]); print(next(a["browser_download_url"] for a in d["assets"] if p.search(a["name"])))' "$regex"
}

echo "Installing latest Metamod:Source Linux build..."
MM_PAGE=$(curl -fsSL https://mms.alliedmods.net/mmsdrop/2.0/mmsource-latest-linux)
MM_FILE=$(printf '%s' "$MM_PAGE" | tr -d '\r\n')
curl -fL "https://mms.alliedmods.net/mmsdrop/2.0/$MM_FILE" -o "$TMP/metamod.tar.gz"
tar -xzf "$TMP/metamod.tar.gz" -C "$CSGO"

echo "Installing latest CounterStrikeSharp with runtime..."
CSS_URL=$(latest_asset_url roflmuffin/CounterStrikeSharp 'with-runtime.*linux.*\.zip$|linux.*with-runtime.*\.zip$')
curl -fL "$CSS_URL" -o "$TMP/css.zip"
unzip -oq "$TMP/css.zip" -d "$CSGO"

if [[ $WITH_MODE_PLUGINS == 0 ]]; then
  echo
  echo "Metamod + CounterStrikeSharp installed into $CSGO."
  echo "Mode plugins were left untouched (they are pinned in git)."
  echo "Next: run cs2-updater in repair-metamod mode to restore the gameinfo.gi search path."
  echo "Pass --with-mode-plugins to also re-download the Retakes / MatchZy mode plugins."
  exit 0
fi

echo "Refreshing pinned mode plugins (--with-mode-plugins) ..."

echo "Installing latest Retakes mode plugin..."
RET_URL=$(latest_asset_url B3none/cs2-retakes '^RetakesPlugin-[0-9].*\.zip$')
rm -rf "$MANAGER_DIR/modes/retake/plugins"/*
curl -fL "$RET_URL" -o "$TMP/retakes.zip"
unzip -oq "$TMP/retakes.zip" -d "$TMP/retakes"
if [[ -d "$TMP/retakes/plugins" ]]; then
  cp -a "$TMP/retakes/plugins/." "$MANAGER_DIR/modes/retake/plugins/"
else
  find "$TMP/retakes" -type f -path '*/plugins/*' -exec cp --parents '{}' "$MANAGER_DIR/modes/retake/plugins/" \;
fi

echo "Installing latest MatchZy mode plugin..."
MZ_URL=$(latest_asset_url shobhit-pathak/MatchZy '\.zip$')
rm -rf "$MANAGER_DIR/modes/faceit/plugins"/*
curl -fL "$MZ_URL" -o "$TMP/matchzy.zip"
unzip -oq "$TMP/matchzy.zip" -d "$TMP/matchzy"
PLUGIN_DIR=$(find "$TMP/matchzy" -type d -path '*/addons/counterstrikesharp/plugins' | head -n1 || true)
if [[ -n "$PLUGIN_DIR" ]]; then
  cp -a "$PLUGIN_DIR/." "$MANAGER_DIR/modes/faceit/plugins/"
else
  echo "MatchZy archive layout was not recognized. Copy its plugin folder manually." >&2
fi

echo "Done. Verify plugin folders (git diff), then run scripts/start.sh."
