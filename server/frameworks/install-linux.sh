#!/usr/bin/env bash
# Installs the exact Metamod and CounterStrikeSharp versions declared in
# server/frameworks/versions.json. It never follows an unpinned "latest" release.

set -euo pipefail

FRAMEWORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${FRAMEWORK_DIR}/../.." && pwd)"
VERSIONS_FILE="${FRAMEWORK_DIR}/versions.json"

[[ -f "${VERSIONS_FILE}" ]] || {
  echo "Missing ${VERSIONS_FILE}" >&2
  exit 1
}

if [[ -z "${CS2_DATA_DIR:-}" ]]; then
  [[ -f "${PROJECT_DIR}/.env" ]] || {
    echo "Missing ${PROJECT_DIR}/.env" >&2
    exit 1
  }

  set -a
  source "${PROJECT_DIR}/.env"
  set +a

  [[ -n "${CS2_DATA_PATH:-}" ]] || {
    echo "CS2_DATA_PATH is not configured" >&2
    exit 1
  }

  CS2_DATA_DIR="${CS2_DATA_PATH}"

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
CSGO="${DATA}/game/csgo"

[[ -f "${DATA}/game/bin/linuxsteamrt64/cs2" ]] || {
  echo "CS2 is not installed at ${DATA}; run cs2-updater first." >&2
  exit 1
}

read_version() {
  python3 - "${VERSIONS_FILE}" "$1" "$2" <<'PY'
import json
import sys

path, component, field = sys.argv[1:]

with open(path, encoding="utf-8") as handle:
    data = json.load(handle)

value = data[component].get(field)

if not isinstance(value, str) or not value:
    raise SystemExit(f"missing {component}.{field} in {path}")

print(value)
PY
}

MM_VERSION="$(read_version metamod version)"
MM_URL="$(read_version metamod url)"

CSS_VERSION="$(read_version counterstrikesharp version)"
CSS_API="$(read_version counterstrikesharp release_api)"
CSS_PATTERN="$(read_version counterstrikesharp asset_pattern)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "${CSGO}"

echo "Installing pinned Metamod ${MM_VERSION} ..."

curl \
  -fL \
  --retry 3 \
  "${MM_URL}" \
  -o "${TMP}/metamod.tar.gz"

tar -tzf "${TMP}/metamod.tar.gz" >/dev/null
tar -xzf "${TMP}/metamod.tar.gz" -C "${CSGO}"

echo "Resolving pinned CounterStrikeSharp ${CSS_VERSION} asset ..."

CSS_URL="$(
  curl \
    -fsSL \
    --retry 3 \
    -H "Accept: application/vnd.github+json" \
    -H "User-Agent: cs2-server-manager" \
    "${CSS_API}" |
  python3 -c '
import json
import re
import sys

release = json.load(sys.stdin)
pattern = re.compile(sys.argv[1], re.I)

assets = [
    asset["browser_download_url"]
    for asset in release.get("assets", [])
    if pattern.search(asset.get("name", ""))
]

if len(assets) != 1:
    raise SystemExit(
        f"expected one matching CounterStrikeSharp asset, found {len(assets)}"
    )

print(assets[0])
' "${CSS_PATTERN}"
)"

echo "Installing pinned CounterStrikeSharp ${CSS_VERSION} ..."

curl \
  -fL \
  --retry 3 \
  "${CSS_URL}" \
  -o "${TMP}/css.zip"

unzip -tq "${TMP}/css.zip" >/dev/null
unzip -oq "${TMP}/css.zip" -d "${CSGO}"

#
# Install repository-managed CounterStrikeSharp configuration.
#
# Source:
#   server/frameworks/counterstrikesharp/configs/
#
# Destination:
#   game/csgo/addons/counterstrikesharp/configs/
#
CUSTOM_CSS_CONFIGS="${FRAMEWORK_DIR}/counterstrikesharp/configs"
CSS_CONFIGS="${CSGO}/addons/counterstrikesharp/configs"

if [[ -d "${CUSTOM_CSS_CONFIGS}" ]]; then
  echo "Installing managed CounterStrikeSharp configuration ..."

  mkdir -p "${CSS_CONFIGS}"
  cp -a "${CUSTOM_CSS_CONFIGS}/." "${CSS_CONFIGS}/"
fi

cat > "${CSGO}/addons/.cs2-manager-versions.json" <<JSON
{
  "metamod": "${MM_VERSION}",
  "counterstrikesharp": "${CSS_VERSION}"
}
JSON

echo "Installed Metamod ${MM_VERSION} and CounterStrikeSharp ${CSS_VERSION}."
echo "Managed CounterStrikeSharp configuration installed from ${CUSTOM_CSS_CONFIGS}."
echo "Run the Metamod repair/validation maintenance action before starting cs2-game."
