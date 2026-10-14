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
CSS_URL="$(read_version counterstrikesharp url)"
MM_SHA="$(read_version metamod sha256)"
CSS_SHA="$(read_version counterstrikesharp sha256)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Download and validate both releases before changing the installed addons.
echo "Downloading pinned Metamod ${MM_VERSION} and CounterStrikeSharp ${CSS_VERSION} ..."
curl -fL --retry 3 --connect-timeout 20 "${MM_URL}" -o "${TMP}/metamod.tar.gz"
curl -fL --retry 3 --connect-timeout 20 "${CSS_URL}" -o "${TMP}/css.zip"
printf '%s  %s\n' "${MM_SHA}" "${TMP}/metamod.tar.gz" "${CSS_SHA}" "${TMP}/css.zip" | sha256sum --check --strict

tar -tzf "${TMP}/metamod.tar.gz" >/dev/null
unzip -tq "${TMP}/css.zip" >/dev/null
mkdir -p "${TMP}/staged" "${CSGO}"
tar -xzf "${TMP}/metamod.tar.gz" -C "${TMP}/staged"
unzip -oq "${TMP}/css.zip" -d "${TMP}/staged"
CSS_ADMINS="${CSGO}/addons/counterstrikesharp/configs/admins.json"
if [[ -f "${CSS_ADMINS}" ]]; then
  cp -a "${CSS_ADMINS}" "${TMP}/admins.saved.json"
fi
cp -a "${TMP}/staged/." "${CSGO}/"
if [[ -f "${TMP}/admins.saved.json" ]]; then
  cp -a "${TMP}/admins.saved.json" "${CSS_ADMINS}"
fi

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
  python3 - "${CUSTOM_CSS_CONFIGS}" "${CSS_CONFIGS}" <<'ADMIN_CONFIG'
import json
import shutil
import sys
from pathlib import Path

source, destination = map(Path, sys.argv[1:])
for path in source.rglob("*"):
    if not path.is_file():
        continue
    target = destination / path.relative_to(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "admins.json":
        existing = json.loads(target.read_text(encoding="utf-8-sig")) if target.exists() else {}
        configured = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(existing, dict) or not isinstance(configured, dict):
            raise SystemExit("CounterStrikeSharp admins must be JSON objects")
        existing.update(configured)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        temp.replace(target)
    else:
        shutil.copy2(path, target)
ADMIN_CONFIG
fi

cat > "${CSGO}/addons/.cs2-manager-versions.json" <<JSON
{
  "metamod": "${MM_VERSION}",
  "counterstrikesharp": "${CSS_VERSION}"
}
JSON

# This installer runs as root, while the runtime container runs as 1000:1000
# (server/runtime/Dockerfile). Archive members keep their original ownership, so
# hand the installed tree back to the game user or mode deployment cannot write
# into addons.
if [[ "${EUID}" -eq 0 ]]; then
  chown -R 1000:1000 "${CSGO}/addons"
fi

echo "Installed Metamod ${MM_VERSION} and CounterStrikeSharp ${CSS_VERSION}."
echo "Managed CounterStrikeSharp configuration installed from ${CUSTOM_CSS_CONFIGS}."
echo "Run the Metamod repair/validation maintenance action before starting cs2-game."
