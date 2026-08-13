"""Updater image preflight and maintenance route hardening.

The main panel module is intentionally kept focused on the UI and server state.
This module installs the updater safeguards at WSGI startup, before requests are
accepted.
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path

DEFAULT_CS2_BASE_IMAGE = (
    "joedwards32/cs2@sha256:"
    "41b826d6280d1aa9e41c866a6d88cc7f523e027f16c47a313b20c2d7a17f2680"
)
MAINTENANCE_LOCK = threading.Lock()


@contextmanager
def maintenance_operation():
    """Allow only one updater or repair workflow to mutate server data."""
    if not MAINTENANCE_LOCK.acquire(blocking=False):
        raise RuntimeError("Another maintenance operation is already running")
    try:
        yield
    finally:
        MAINTENANCE_LOCK.release()


def _emit_build_logs(job, logs) -> None:
    for row in logs:
        if not isinstance(row, dict):
            continue
        message = row.get("stream") or row.get("status")
        if message:
            job.emit(str(message).rstrip())


def ensure_updater_image(panel, job):
    """Return the local updater image, building it when it is absent.

    The returned Docker image object is later referenced by immutable image ID.
    This prevents ContainerCollection.run from treating a missing local tag as a
    registry image that should be pulled.
    """
    if not panel.CS2_DATA_PATH_HOST:
        raise RuntimeError("CS2_DATA_PATH is not configured for the panel")

    try:
        return panel.client.images.get(panel.UPDATER_IMAGE)
    except panel.NotFound:
        pass

    source = Path(
        os.environ.get(
            "UPDATER_BUILD_CONTEXT",
            str(panel.PROJECT_DIR / "server/updater"),
        )
    )
    if not (source / "Dockerfile").is_file():
        raise RuntimeError(
            f"Updater image {panel.UPDATER_IMAGE} is missing and build context "
            f"{source} does not contain a Dockerfile"
        )

    job.emit(
        f"Updater image {panel.UPDATER_IMAGE} is missing locally. "
        f"Building it from {source}."
    )
    build_kwargs = {
        "path": str(source),
        "tag": panel.UPDATER_IMAGE,
        "rm": True,
        "pull": False,
    }
    base_image = os.environ.get("CS2_BASE_IMAGE", DEFAULT_CS2_BASE_IMAGE).strip()
    if base_image:
        build_kwargs["buildargs"] = {"CS2_BASE_IMAGE": base_image}

    _image, logs = panel.client.images.build(**build_kwargs)
    _emit_build_logs(job, logs)

    try:
        image = panel.client.images.get(panel.UPDATER_IMAGE)
    except panel.NotFound as exc:
        raise RuntimeError(
            f"Docker completed the updater build but {panel.UPDATER_IMAGE} "
            "is still unavailable locally"
        ) from exc

    job.emit(f"Updater image ready locally as {image.id}.")
    return image


def run_updater_container(panel, job, updater_mode: str) -> int:
    image = ensure_updater_image(panel, job)
    name = f"cs2-updater-job-{job.id}"

    try:
        panel.client.containers.get(name).remove(force=True)
    except panel.NotFound:
        pass

    container = panel.client.containers.run(
        image.id,
        detach=True,
        name=name,
        environment={
            "CS2_UPDATER_MODE": updater_mode,
            "CS2_UPDATER_CONFIRM": panel.UPDATER_CONFIRM_PHRASE,
        },
        volumes={
            panel.CS2_DATA_PATH_HOST: {
                "bind": "/home/steam/cs2-dedicated",
                "mode": "rw",
            }
        },
    )
    try:
        for chunk in container.logs(stream=True, follow=True):
            job.emit(chunk.decode("utf-8", errors="replace").rstrip())
        return container.wait().get("StatusCode", -1)
    finally:
        try:
            container.remove(force=True)
        except panel.DockerException:
            pass


def gameinfo_has_active_metamod(path: Path) -> bool | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    waiting_for_brace = False
    in_search_paths = False

    for raw in lines:
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue

        if not in_search_paths and re.fullmatch(r"SearchPaths\s*\{?", line):
            if line.endswith("{"):
                in_search_paths = True
            else:
                waiting_for_brace = True
            continue

        if waiting_for_brace:
            if line == "{":
                in_search_paths = True
                waiting_for_brace = False
            continue

        if in_search_paths and line.startswith("}"):
            return False

        if in_search_paths and re.fullmatch(
            r"Game\s+csgo/addons/metamod",
            line,
        ):
            return True

    return False


def _steamcmd_workflow(panel, kind: str, updater_mode: str):
    if (
        (panel.request.get_json(silent=True) or {}).get("confirm")
        != panel.UPDATER_CONFIRM_PHRASE
    ):
        return panel.jsonify(
            {
                "ok": False,
                "error": (
                    "Owner confirmation required: "
                    f"{panel.UPDATER_CONFIRM_PHRASE}"
                ),
            }
        ), 403

    restore = panel._mode_to_restore()

    def worker(job):
        with maintenance_operation():
            ensure_updater_image(panel, job)
            job.emit(
                "Creating a manager configuration backup. "
                "The CS2 installation directory is not copied."
            )
            panel.make_backup(job, f"pre-{kind}")
            with panel.OPERATION_LOCK:
                panel.stop_game()
            if run_updater_container(panel, job, updater_mode) != 0:
                raise RuntimeError(f"SteamCMD {updater_mode} failed")
            panel.STATE_TIMESTAMPS["last_manual_update"] = panel.now_iso()
            if restore and not panel.restart_previous_mode(job, restore):
                raise RuntimeError("Post-update verification failed")
            job.result = {"mode": updater_mode, "restored": restore}

    return panel.jsonify(
        {"ok": True, "job": panel.start_job(kind, worker).to_dict()}
    ), 202


def _repair_metamod_handler(panel):
    restore = panel._mode_to_restore()

    def worker(job):
        with maintenance_operation():
            ensure_updater_image(panel, job)
            job.emit(
                "Creating a manager configuration backup. "
                "The CS2 installation directory is not copied."
            )
            panel.make_backup(job, "pre-repair")
            with panel.OPERATION_LOCK:
                panel.stop_game()
            if run_updater_container(panel, job, "repair-metamod") != 0:
                raise RuntimeError("Metamod repair failed")
            if restore and not panel.restart_previous_mode(job, restore):
                raise RuntimeError("Post-repair restart failed")
            job.result = {"gameinfo_metamod": panel.gameinfo_has_metamod()}

    return panel.jsonify(
        {"ok": True, "job": panel.start_job("repair-metamod", worker).to_dict()}
    ), 202


def install(panel) -> None:
    """Install updater safeguards into the loaded panel module once."""
    if getattr(panel, "_UPDATER_GUARD_INSTALLED", False):
        return

    panel.run_updater_container = lambda job, mode: run_updater_container(
        panel,
        job,
        mode,
    )
    panel._run_steamcmd_workflow = lambda kind, mode: _steamcmd_workflow(
        panel,
        kind,
        mode,
    )
    panel.gameinfo_has_metamod = lambda: gameinfo_has_active_metamod(
        panel.SERVER_DIR / "game/csgo/gameinfo.gi"
    )

    def api_repair_metamod():
        return _repair_metamod_handler(panel)

    guarded_repair = panel.require_auth(api_repair_metamod)
    panel.app.view_functions["api_repair_metamod"] = guarded_repair
    panel.api_repair_metamod = guarded_repair
    panel._UPDATER_GUARD_INSTALLED = True
