#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ZIP_SHA256="42e4672e48e8b8b460180648a2f2508787b6f77896323cfe594661c692507c7b"
EXPECTED_VERSION="v1.0.0"

usage() {
    echo "Usage: $0 /path/to/HeroShift-v1.0.0.zip [project-root] [--stage-only]" >&2
    exit 2
}

[[ $# -ge 1 && $# -le 3 ]] || usage
[[ $# -lt 3 || "$3" == "--stage-only" ]] || usage
PACKAGE_PATH="$(realpath "$1")"
PROJECT_ROOT="$(realpath "${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}")"
STAGE_ONLY="${3:-}"
ENV_FILE="${PROJECT_ROOT}/.env"
RELEASE_RELATIVE="./manager/releases/heroshift/v1.0.0"
RELEASE_ROOT="${PROJECT_ROOT}/manager/releases/heroshift/v1.0.0"

[[ -f "${PACKAGE_PATH}" ]] || { echo "Package not found: ${PACKAGE_PATH}" >&2; exit 1; }
[[ -f "${PROJECT_ROOT}/compose.yml" ]] || { echo "compose.yml not found under ${PROJECT_ROOT}" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
if [[ "${STAGE_ONLY}" != "--stage-only" ]]; then
    command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
fi

actual_zip_sha="$(sha256sum "${PACKAGE_PATH}" | awk '{print $1}')"
[[ "${actual_zip_sha}" == "${EXPECTED_ZIP_SHA256}" ]] || {
    echo "Unexpected package SHA256: ${actual_zip_sha}" >&2
    exit 1
}

mkdir -p "${PROJECT_ROOT}/manager/releases/heroshift" "${PROJECT_ROOT}/manager/backups"
backup_root="${PROJECT_ROOT}/manager/backups/heroshift-release-$(date -u +%Y%m%d-%H%M%S)"

python3 - "${PACKAGE_PATH}" "${RELEASE_ROOT}" "${backup_root}" "${EXPECTED_VERSION}" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

package = Path(sys.argv[1])
destination = Path(sys.argv[2])
backup = Path(sys.argv[3])
expected_version = sys.argv[4]

with zipfile.ZipFile(package) as archive:
    names = archive.namelist()
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise SystemExit(f"Unsafe ZIP path: {name}")

    manifest = json.loads(archive.read("package-manifest.json"))
    if manifest.get("package") != "HeroShift":
        raise SystemExit("Package manifest is not HeroShift")
    if manifest.get("version") != expected_version:
        raise SystemExit(
            f"Expected {expected_version}, got {manifest.get('version')!r}"
        )

    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise SystemExit("Package manifest has no files")

    for row in rows:
        name = row.get("path")
        data = archive.read(name)
        actual_hash = hashlib.sha256(data).hexdigest()
        if len(data) != row.get("size") or actual_hash != row.get("sha256"):
            raise SystemExit(f"Manifest verification failed for {name}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".heroshift-v1.0.0-", dir=destination.parent
    ) as temporary:
        temporary_path = Path(temporary)
        extracted = temporary_path / "package"
        staged = temporary_path / "release"
        archive.extractall(extracted)

        mappings = [
            (
                extracted / "addons/counterstrikesharp/plugins/HeroShift",
                staged / "plugins/HeroShift",
            ),
            (
                extracted / "addons/counterstrikesharp/gamedata/HeroShift.gamedata.json",
                staged / "gamedata/HeroShift.gamedata.json",
            ),
            (
                extracted / "addons/metamod/RayTrace.vdf",
                staged / "utils/RayTrace/addons/metamod/RayTrace.vdf",
            ),
            (
                extracted / "addons/RayTrace",
                staged / "utils/RayTrace/addons/RayTrace",
            ),
            (
                extracted / "addons/counterstrikesharp/plugins/RayTraceImpl",
                staged / "utils/RayTrace/addons/counterstrikesharp/plugins/RayTraceImpl",
            ),
            (
                extracted / "addons/counterstrikesharp/shared/RayTraceApi",
                staged / "utils/RayTrace/addons/counterstrikesharp/shared/RayTraceApi",
            ),
        ]

        for source, target in mappings:
            if not source.exists():
                raise SystemExit(f"Required package path is missing: {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

        shutil.copy2(extracted / "package-manifest.json", staged / "package-manifest.json")
        if (extracted / "THIRD_PARTY_NOTICES.md").is_file():
            shutil.copy2(
                extracted / "THIRD_PARTY_NOTICES.md",
                staged / "THIRD_PARTY_NOTICES.md",
            )
        if (extracted / "licenses").is_dir():
            shutil.copytree(extracted / "licenses", staged / "licenses")

        marker = {
            "package": "HeroShift",
            "version": expected_version,
            "archive_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        }
        (staged / "installed-release.json").write_text(
            json.dumps(marker, indent=2) + "\n", encoding="utf-8"
        )

        existing_releases = sorted(
            path for path in destination.parent.glob("v*") if path.is_dir()
        )
        if existing_releases:
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.mkdir(parents=True, exist_ok=False)
            for existing in existing_releases:
                shutil.move(str(existing), str(backup / existing.name))
        os.replace(staged, destination)

print(f"Installed verified release overlay at {destination}")
PY

if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${PROJECT_ROOT}/.env.example" "${ENV_FILE}"
fi

python3 - "${ENV_FILE}" "${RELEASE_RELATIVE}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
value = sys.argv[2]
key = "HEROSHIFT_RELEASE_PATH"
lines = path.read_text(encoding="utf-8").splitlines()
updated = []
replaced = False
for line in lines:
    if line.startswith(key + "="):
        updated.append(f"{key}={value}")
        replaced = True
    else:
        updated.append(line)
if not replaced:
    if updated and updated[-1]:
        updated.append("")
    updated.append(f"{key}={value}")
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY

if [[ "${STAGE_ONLY}" == "--stage-only" ]]; then
    echo "HeroShift ${EXPECTED_VERSION} is staged as the active release overlay."
    exit 0
fi

cd "${PROJECT_ROOT}"
docker compose config --quiet

was_running="false"
if docker inspect cs2-game >/dev/null 2>&1; then
    was_running="$(docker inspect --format '{{.State.Running}}' cs2-game)"
fi

docker compose up -d --force-recreate --no-deps panel
if [[ "${was_running}" == "true" ]]; then
    docker compose up -d --force-recreate --no-deps cs2-game
else
    docker compose create --force-recreate cs2-game
fi

echo "HeroShift ${EXPECTED_VERSION} is installed as the active release overlay."
if [[ "${was_running}" == "true" ]]; then
    echo "The game container was recreated. Check the panel health and game logs."
else
    echo "The game container remains stopped. Start or switch to HeroShift from the panel."
fi
