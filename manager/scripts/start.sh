#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

[[ -f .env ]] || cp .env.example .env

if compgen -G "$ROOT/HeroShift-v*.zip" >/dev/null; then
  "$ROOT/install-heroshift.sh" --stage-only
fi

release_path="$(grep -E '^HEROSHIFT_RELEASE_PATH=' .env | tail -n 1 | cut -d= -f2- || true)"
release_path="${release_path:-./manager/releases/heroshift/current}"
if [[ "$release_path" = /* ]]; then
  release_root="$release_path"
else
  release_root="$ROOT/${release_path#./}"
fi

if [[ ! -f "$release_root/installed-release.json" ]]; then
  echo "HeroShift is not installed." >&2
  echo "Place HeroShift-vX.Y.Z.zip in the repository root and run ./install-heroshift.sh" >&2
  exit 1
fi

docker compose config --quiet
docker compose create cs2-game
docker compose up -d --build panel
echo "Panel started. Select a mode to deploy and start cs2-game."
