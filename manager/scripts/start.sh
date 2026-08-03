#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || cp .env.example .env
# Create the four game services (stopped) from the pinned runtime image, then
# launch the panel. The updater stays in the "maintenance" profile (not started).
docker compose create cs2-faceit cs2-retakes cs2-superheroes cs2-gungame
docker compose up -d --build panel
echo "Panel started. Open the address configured by PANEL_BIND:PANEL_PORT."
