#!/usr/bin/env bash
# Docker-only bootstrap for Linux and Intel macOS. No host Python is needed.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
command -v docker >/dev/null || { echo "Install Docker Engine or Docker Desktop first." >&2; exit 1; }
docker info >/dev/null
docker compose version >/dev/null
arch="$(docker info --format '{{.Architecture}}')"
case "$arch" in
  amd64|x86_64) ;;
  *) echo "CS2 requires an amd64 engine. Detected: $arch. Use an x86-64 machine." >&2; exit 1 ;;
esac

if [[ ! -f .env ]]; then
  umask 077
  cp .env.example .env
  panel_secret="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  rcon_secret="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  # No eval/source: .env uses Compose syntax and may contain operator input.
  awk -v panel="$panel_secret" -v rcon="$rcon_secret" '
    /^PANEL_PASSWORD=/ { print "PANEL_PASSWORD=" panel; next }
    /^CS2_RCON_PASSWORD=/ { print "CS2_RCON_PASSWORD=" rcon; next }
    { print }
  ' .env > .env.tmp
  mv .env.tmp .env
  echo "Created .env with generated panel and RCON passwords."
fi

docker compose config --quiet
# Re-running setup must never install addons beside a running game process.
docker compose stop cs2-game
docker compose --profile maintenance build cs2-updater cs2-modinstaller
docker compose --profile maintenance run --rm cs2-init
# SteamCMD reuses installed files on repeat runs and only downloads updates.
docker compose --profile maintenance run --rm \
  -e CS2_UPDATER_MODE=update -e 'CS2_UPDATER_CONFIRM=UPDATE CS2' cs2-updater
docker compose --profile maintenance run --rm cs2-modinstaller
docker compose --profile maintenance run --rm \
  -e CS2_UPDATER_MODE=repair-metamod -e 'CS2_UPDATER_CONFIRM=UPDATE CS2' cs2-updater
docker compose create cs2-game
docker compose up -d --build --no-deps panel
echo "Setup complete. Open the panel on the PANEL_BIND/PANEL_PORT configured in .env."
echo "Default: http://127.0.0.1:8080. Login with PANEL_USERNAME and PANEL_PASSWORD from .env."
echo "Choose FaceIt or Retakes and press Start."
