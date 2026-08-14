#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

[[ -f .env ]] || {
  echo "Missing .env. Run setup.ps1 on the Windows host first." >&2
  exit 1
}

docker compose config --quiet
docker compose create --build cs2-game
docker compose up -d --build --no-deps panel
echo "Panel started. cs2-game remains stopped until a mode is selected."
