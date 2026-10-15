#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

[[ -f .env ]] || {
  echo "Missing .env. Run server/scripts/setup.sh or server/scripts/setup.ps1 first." >&2
  exit 1
}

bash server/scripts/setup.sh
