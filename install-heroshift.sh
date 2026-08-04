#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_PATH=""
STAGE_ONLY="false"

usage() {
  cat >&2 <<'USAGE'
Usage: ./install-heroshift.sh [HeroShift-vX.Y.Z.zip] [--stage-only]

When no package is supplied, the highest semantic version matching
HeroShift-v*.zip in the repository root is selected automatically.
USAGE
  exit 2
}

for argument in "$@"; do
  case "$argument" in
    --stage-only)
      STAGE_ONLY="true"
      ;;
    -h|--help)
      usage
      ;;
    *)
      [[ -z "$PACKAGE_PATH" ]] || usage
      PACKAGE_PATH="$argument"
      ;;
  esac
done

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required" >&2
  exit 1
}

set +e
python3 - "$ROOT" "$PACKAGE_PATH" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve()
explicit_package = sys.argv[2].strip()
package_pattern = re.compile(r"^HeroShift-(v\d+\.\d+\.\d+)\.zip$")
version_pattern = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def version_key(version: str) -> tuple[int, int, int]:
    match = version_pattern.fullmatch(version)
    if not match:
        raise SystemExit(f"Unsupported HeroShift version: {version}")
    return tuple(int(part) for part in match.groups())


def select_package() -> Path:
    if explicit_package:
        candidate = Path(explicit_package)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise SystemExit(f"Package not found: {candidate}")
        return candidate

    candidates: list[tuple[tuple[int, int, int], Path]] = []
    for candidate in root.glob("HeroShift-v*.zip"):
        match = package_pattern.fullmatch(candidate.name)
        if match:
            candidates.append((version_key(match.group(1)), candidate.resolve()))

    if not candidates:
        raise SystemExit(
            "No HeroShift package found in the repository root. "
            "Expected HeroShift-vX.Y.Z.zip"
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def safe_member(name: str) -> PurePosixPath:
    if "\\" in name:
        raise SystemExit(f"Unsafe ZIP path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"Unsafe ZIP path: {name}")
    return path


def set_env_value(path: Path, name: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{name}={value}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(name + "="):
            updated.append(replacement)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1]:
            updated.append("")
        updated.append(replacement)
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


package = select_package()
archive_hash = hashlib.sha256(package.read_bytes()).hexdigest()
required_paths = {
    "addons/counterstrikesharp/plugins/HeroShift",
    "addons/counterstrikesharp/gamedata/HeroShift.gamedata.json",
    "addons/metamod/RayTrace.vdf",
    "addons/RayTrace",
    "addons/counterstrikesharp/plugins/RayTraceImpl",
    "addons/counterstrikesharp/shared/RayTraceApi",
}

with zipfile.ZipFile(package) as archive:
    names = archive.namelist()
    normalized_names = {str(safe_member(name)).rstrip("/") for name in names}
    if "package-manifest.json" not in normalized_names:
        raise SystemExit("package-manifest.json is missing")

    manifest = json.loads(archive.read("package-manifest.json"))
    if manifest.get("package") != "HeroShift":
        raise SystemExit("Package manifest is not HeroShift")

    version = str(manifest.get("version", ""))
    version_key(version)
    expected_filename = f"HeroShift-{version}.zip"
    if package.name != expected_filename:
        raise SystemExit(
            f"Package filename must be {expected_filename}, got {package.name}"
        )

    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise SystemExit("Package manifest has no files")

    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit("Package manifest contains an invalid file row")
        name = str(safe_member(str(row.get("path", ""))))
        if not name or name in seen:
            raise SystemExit(f"Duplicate or empty manifest path: {name}")
        seen.add(name)
        try:
            info = archive.getinfo(name)
        except KeyError as error:
            raise SystemExit(f"Manifest file is missing: {name}") from error
        data = archive.read(info)
        actual_hash = hashlib.sha256(data).hexdigest()
        if info.file_size != row.get("size") or actual_hash != row.get("sha256"):
            raise SystemExit(f"Manifest verification failed for {name}")

    for required in required_paths:
        if not any(name == required or name.startswith(required + "/") for name in normalized_names):
            raise SystemExit(f"Required package path is missing: {required}")

release_parent = root / "manager" / "releases" / "heroshift"
destination = release_parent / "current"
backup_parent = root / "manager" / "backups"
env_path = root / ".env"
env_example = root / ".env.example"
release_relative = "./manager/releases/heroshift/current"

marker_path = destination / "installed-release.json"
if marker_path.is_file():
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        marker = {}
    if marker.get("archive_sha256") == archive_hash and marker.get("version") == version:
        if not env_path.exists():
            shutil.copy2(env_example, env_path)
        set_env_value(env_path, "HEROSHIFT_RELEASE_PATH", release_relative)
        print(f"HeroShift {version} is already installed from {package.name}")
        raise SystemExit(10)

release_parent.mkdir(parents=True, exist_ok=True)
backup_parent.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory(prefix=".heroshift-install-", dir=release_parent) as temporary:
    temporary_path = Path(temporary)
    extracted = temporary_path / "package"
    staged = temporary_path / "release"
    with zipfile.ZipFile(package) as archive:
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
    notice = extracted / "THIRD_PARTY_NOTICES.md"
    if notice.is_file():
        shutil.copy2(notice, staged / notice.name)
    licenses = extracted / "licenses"
    if licenses.is_dir():
        shutil.copytree(licenses, staged / "licenses")

    marker = {
        "package": "HeroShift",
        "version": version,
        "archive_sha256": archive_hash,
        "source_archive": package.name,
        "installed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (staged / "installed-release.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )

    if destination.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        previous_version = "unknown"
        try:
            previous_marker = json.loads(marker_path.read_text(encoding="utf-8"))
            previous_version = str(previous_marker.get("version", "unknown"))
        except (OSError, json.JSONDecodeError):
            pass
        backup = backup_parent / f"heroshift-{previous_version}-{timestamp}"
        shutil.move(str(destination), str(backup))
        print(f"Previous HeroShift overlay backed up to {backup}")

    os.replace(staged, destination)

if not env_path.exists():
    if not env_example.is_file():
        raise SystemExit(f"Missing {env_example}")
    shutil.copy2(env_example, env_path)
set_env_value(env_path, "HEROSHIFT_RELEASE_PATH", release_relative)

print(f"Installed verified HeroShift {version} from {package.name}")
print(f"Active overlay: {destination}")
PY
status=$?
set -e

if [[ $status -eq 10 && "$STAGE_ONLY" == "true" ]]; then
  exit 0
fi
if [[ $status -ne 0 && $status -ne 10 ]]; then
  exit "$status"
fi

if [[ "$STAGE_ONLY" == "true" ]]; then
  echo "HeroShift was staged. Docker containers were not changed."
  exit 0
fi

command -v docker >/dev/null 2>&1 || {
  echo "docker is required unless --stage-only is used" >&2
  exit 1
}

cd "$ROOT"
docker compose config --quiet

was_running="false"
game_exists="false"
if docker inspect cs2-game >/dev/null 2>&1; then
  game_exists="true"
  was_running="$(docker inspect --format '{{.State.Running}}' cs2-game)"
fi

docker compose up -d --force-recreate --no-deps panel
if [[ "$was_running" == "true" ]]; then
  docker compose up -d --force-recreate --no-deps cs2-game
elif [[ "$game_exists" == "true" ]]; then
  docker compose create --force-recreate cs2-game
else
  docker compose create cs2-game
fi

echo "HeroShift is installed. No Docker image was rebuilt."
if [[ "$was_running" == "true" ]]; then
  echo "The game container was recreated so the new files are active."
else
  echo "The game container remains stopped. Start HeroShift from the panel."
fi
