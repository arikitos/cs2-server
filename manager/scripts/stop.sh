#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
docker compose stop cs2-faceit cs2-retakes cs2-superheroes cs2-gungame panel
