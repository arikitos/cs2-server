#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || cp .env.example .env
docker compose config --quiet
docker compose create cs2-game
docker compose up -d --build panel
echo "Panel started. Select a mode to deploy and start cs2-game."
