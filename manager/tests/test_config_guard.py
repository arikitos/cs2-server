from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "manager" / "panel"


def load_config_guard():
    spec = importlib.util.spec_from_file_location(
        "config_guard",
        PANEL / "config_guard.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ConfigGuardTests(unittest.TestCase):
    def test_saved_runtime_settings_are_replayed_after_ready(self) -> None:
        guard = load_config_guard()
        commands: list[tuple[str, str, int]] = []
        timestamps = {"last_config_apply": None}
        panel = SimpleNamespace(
            GAME_CONTAINER="cs2-game",
            STATE_TIMESTAMPS=timestamps,
            validate_mode_settings=lambda mode, settings: dict(settings),
            load_mode=lambda mode: {"hostname": "Saved", "freezetime": 4},
            hot_convar_lines=lambda settings: [
                'hostname "Saved"',
                "mp_freezetime 4",
            ],
            selected_format=lambda mode, settings: {"cfg": ["mp_maxrounds 12"]},
            rcon_command=lambda container, command, timeout: commands.append(
                (container, command, timeout)
            ),
            now_iso=lambda: "2026-08-04T15:00:00+00:00",
        )

        settings = guard.apply_saved_runtime(panel, "heroshift")

        self.assertEqual(settings["hostname"], "Saved")
        self.assertEqual(
            commands,
            [
                ("cs2-game", 'hostname "Saved"', 5),
                ("cs2-game", "mp_freezetime 4", 5),
                ("cs2-game", "mp_maxrounds 12", 5),
            ],
        )
        self.assertEqual(
            timestamps["last_config_apply"],
            "2026-08-04T15:00:00+00:00",
        )

    def test_heroshift_config_is_manager_owned(self) -> None:
        mode_root = ROOT / "manager" / "modes" / "heroshift"
        manifest = json.loads((mode_root / "mode.json").read_text(encoding="utf-8"))
        configs = {entry["name"]: entry for entry in manifest["configs"]}

        self.assertIn("heroshift.json", configs)
        self.assertNotIn("config.json", configs)
        self.assertNotIn("skillsInfo.json", configs)
        self.assertEqual(
            configs["heroshift.json"]["target"],
            "addons/counterstrikesharp/plugins/HeroShift/configs/heroshift.json",
        )
        config = json.loads(
            (mode_root / configs["heroshift.json"]["source"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(configs["heroshift.json"]["source"], "config/heroshift.json")
        self.assertEqual(config, {"schemaVersion": 1})

    def test_guard_is_loaded_by_wsgi_image(self) -> None:
        dockerfile = (PANEL / "Dockerfile").read_text(encoding="utf-8")
        wsgi = (PANEL / "wsgi.py").read_text(encoding="utf-8")
        self.assertIn("COPY config_guard.py .", dockerfile)
        self.assertIn("install_config_guard(panel)", wsgi)


if __name__ == "__main__":
    unittest.main()
