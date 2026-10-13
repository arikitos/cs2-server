"""Runtime configuration safeguards installed around the existing panel app."""

from __future__ import annotations

import threading
import time


def apply_saved_runtime(panel, mode: str) -> dict:
    """Replay persisted panel settings after CS2 and its game mode are ready."""
    settings = panel.validate_mode_settings(mode, panel.load_mode(mode))
    commands = panel.hot_convar_lines(mode, settings)
    if panel.panel_control_enabled(mode, "format"):
        commands.extend(panel.selected_format(mode, settings).get("cfg", []))
    for command in commands:
        panel.rcon_command(panel.GAME_CONTAINER, command, 5)
    panel.STATE_TIMESTAMPS["last_config_apply"] = panel.now_iso()
    return settings


def _queue_runtime_ready(panel, mode: str, rollback: tuple[str, dict] | None = None) -> None:
    if not panel.RCON_PASSWORD:
        return
    generation = panel.next_rcon_generation()

    def worker() -> None:
        deadline = time.monotonic() + panel.RCON_APPLY_TIMEOUT
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            with panel.RCON_JOB_LOCK:
                if generation != panel.RCON_JOB_GENERATION:
                    return
            if panel.rcon_reachable(panel.GAME_CONTAINER):
                try:
                    settings = apply_saved_runtime(panel, mode)
                except (OSError, RuntimeError, ValueError, PermissionError) as exc:
                    last_error = exc
                    panel.app.logger.warning(
                        "post-ready settings apply failed for %s, retrying: %s",
                        mode,
                        exc,
                    )
                    time.sleep(2)
                    continue
                panel.STATE_TIMESTAMPS["last_successful_start"] = panel.now_iso()
                panel.app.logger.info(
                    "%s is ready in %s with %d persisted settings",
                    mode,
                    panel.GAME_CONTAINER,
                    len(settings),
                )
                return
            time.sleep(2)

        if last_error is not None:
            panel.app.logger.error(
                "runtime settings could not be applied for %s: %s",
                mode,
                last_error,
            )
        else:
            panel.app.logger.error("RCON readiness timed out for %s", mode)
        if rollback is None:
            return

        previous_mode, previous_settings = rollback
        with panel.RCON_JOB_LOCK:
            if generation != panel.RCON_JOB_GENERATION:
                return
        try:
            panel.write_runtime_cfg(previous_mode, previous_settings)
            panel.write_active_mode_state(previous_mode, previous_settings)
            server = panel.load_server()
            server["last_mode"] = previous_mode
            panel.save_server(server)
            with panel.OPERATION_LOCK:
                panel.client.containers.get(panel.GAME_CONTAINER).restart(timeout=20)
            panel.app.logger.error(
                "Rolled back failed mode %s to %s and restarted %s",
                mode,
                previous_mode,
                panel.GAME_CONTAINER,
            )
            panel.audit(
                "mode.rollback",
                "started",
                f"failed={mode} restored={previous_mode}",
                target=previous_mode,
            )
            panel.queue_runtime_ready(previous_mode)
        except (panel.DockerException, OSError, ValueError) as exc:
            panel.app.logger.exception("Automatic mode rollback failed: %s", exc)

    threading.Thread(target=worker, daemon=True, name=f"ready-{mode}").start()


def install(panel) -> None:
    """Install once at WSGI startup."""
    if getattr(panel, "_CONFIG_GUARD_INSTALLED", False):
        return

    def queue_runtime_ready(mode: str, rollback: tuple[str, dict] | None = None) -> None:
        _queue_runtime_ready(panel, mode, rollback)

    panel.queue_runtime_ready = queue_runtime_ready
    panel._CONFIG_GUARD_INSTALLED = True
