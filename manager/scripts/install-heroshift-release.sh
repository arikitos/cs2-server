#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGE_PATH=""
STAGE_ONLY="false"

if [[ $# -ge 1 && "$1" != "--stage-only" ]]; then
  PACKAGE_PATH="$1"
fi
for argument in "$@"; do
  if [[ "$argument" == "--stage-only" ]]; then
    STAGE_ONLY="true"
  fi
done

command=("bash" "$ROOT/install-heroshift.sh")
if [[ -n "$PACKAGE_PATH" ]]; then
  command+=("$PACKAGE_PATH")
fi
if [[ "$STAGE_ONLY" == "true" ]]; then
  command+=("--stage-only")
fi

exec "${command[@]}"
