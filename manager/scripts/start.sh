#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

[[ -f .env ]] || cp .env.example .env

if find "$ROOT/installs" -type f -name '*.zip' -print -quit 2>/dev/null | grep -q .; then
  echo "Package archives are waiting under installs/. Run pwsh ./update.ps1 before starting if they should be applied."
fi

docker compose config --quiet
docker compose create cs2-game
docker compose up -d --build panel
echo "Panel started. Select a mode to deploy and start cs2-game."
