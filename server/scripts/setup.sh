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
umask 077
mkdir -p server/cs2 server/state/runtime server/state/configs server/state/backups
# Compose resolves .env, overrides, paths and ports without pulling any images.
# This local file contains secrets and stays inside the ignored state directory.
runtime_config=server/state/runtime/compose-runtime.json
trap 'rm -f "${runtime_config}.tmp"' EXIT
docker compose --profile game --profile maintenance config --format json > "${runtime_config}.tmp"
mv "${runtime_config}.tmp" "$runtime_config"
echo "Building and starting only the panel (no game downloads)."
docker compose up -d --build --no-deps panel
echo "Setup complete. Open the panel on the PANEL_BIND/PANEL_PORT configured in .env."
echo "Default: http://127.0.0.1:8080. Login with PANEL_USERNAME and PANEL_PASSWORD from .env."
echo "Install the server from Maintenance > Install server, then choose FaceIt or Retakes."
