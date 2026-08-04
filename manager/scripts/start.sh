#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || cp .env.example .env
if [[ ! -f manager/releases/heroshift/v1.0.0/installed-release.json ]]; then
  manager/scripts/install-heroshift-release.sh \
    manager/scripts/HeroShift-v1.0.0.zip \
    "$ROOT" \
    --stage-only
fi
docker compose config --quiet
docker compose create cs2-game
docker compose up -d --build panel
echo "Panel started. Select a mode to deploy and start cs2-game."
