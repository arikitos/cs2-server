from __future__ import annotations

import importlib.util
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "panel"
sys.path.insert(0, str(PANEL))

import config_guard  # noqa: E402


class DummyFlask:
    def __init__(self, *_args, **_kwargs):
        self.logger = logging.getLogger("panel-test")
        self.routes = []

    def _decorator(self, rule, methods):
        def register(function):
            self.routes.append((rule, tuple(methods), function.__name__))
            return function

        return register

    def get(self, rule):
        return self._decorator(rule, ["GET"])

    def post(self, rule):
        return self._decorator(rule, ["POST"])

    def put(self, rule):
        return self._decorator(rule, ["PUT"])

    def route(self, rule, methods=None):
        return self._decorator(rule, methods or ["GET"])


class DummyRequest:
    authorization = None
    remote_addr = "127.0.0.1"
    args = {}

    @staticmethod
    def get_json(silent=True):
        return {}


class DummyContainer:
    def __init__(self, status="created"):
        self.status = status
        self.attrs = {"State": {"StartedAt": None}, "RestartCount": 0}
        self.started = 0
        self.restarted = 0

    def reload(self):
        return None

    def start(self):
        self.started += 1
        self.status = "running"

    def restart(self, timeout=20):
        self.restarted += 1
        self.status = "running"


class DummyContainers:
    def __init__(self, container):
        self.container = container

    def get(self, name):
        if name != "cs2-game":
            raise AssertionError(name)
        return self.container


class DummyClient:
    def __init__(self, container):
        self.containers = DummyContainers(container)


class PanelRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.temp_root = Path(cls.temp.name)
        cls.saved_environment = dict(os.environ)
        os.environ.update(
            {
                "PANEL_DATA_DIR": str(cls.temp_root / "state"),
                "PANEL_MODES_DIR": str(ROOT / "modes"),
                "PANEL_PROJECT_DIR": str(ROOT),
                "PANEL_SERVER_DIR": str(cls.temp_root / "server"),
                "GAME_CONTAINER": "cs2-game",
                "PANEL_PASSWORD": "test-password",
            }
        )

        flask = types.ModuleType("flask")
        flask.Flask = DummyFlask
        flask.Response = lambda *args, **kwargs: (args, kwargs)
        flask.jsonify = lambda value=None, **kwargs: value if value is not None else kwargs
        flask.has_request_context = lambda: False
        flask.render_template = lambda name: name
        flask.request = DummyRequest()
        sys.modules["flask"] = flask

        docker = types.ModuleType("docker")
        docker.from_env = lambda: DummyClient(DummyContainer())
        errors = types.ModuleType("docker.errors")
        errors.DockerException = type("DockerException", (Exception,), {})
        errors.NotFound = type("NotFound", (errors.DockerException,), {})
        docker.errors = errors
        sys.modules["docker"] = docker
        sys.modules["docker.errors"] = errors

        spec = importlib.util.spec_from_file_location("panel_app_test", PANEL / "app.py")
        cls.panel = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.panel)

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.saved_environment)
        sys.modules.pop("panel_app_test", None)
        cls.temp.cleanup()

    def test_panel_discovers_new_mode_ids(self):
        self.assertEqual(
            list(self.panel.MODES),
            ["matchzy", "retakes", "heroshift", "warcraft"],
        )
        self.assertEqual({item["container"] for item in self.panel.MODES.values()}, {"cs2-game"})

    def test_runtime_cfg_is_written_to_operator_state(self):
        settings = self.panel.validate_mode_settings("matchzy", {})
        self.panel.write_runtime_cfg("matchzy", settings)
        path = self.panel.runtime_cfg_path("matchzy")
        self.assertTrue(path.is_file())
        self.assertTrue(path.is_relative_to(self.panel.DATA_DIR))
        self.assertFalse((ROOT / "modes/matchzy/cfg/panel_runtime.cfg").exists())

    def test_start_writes_state_and_starts_single_container(self):
        container = DummyContainer("created")
        self.panel.client = DummyClient(container)
        self.panel.queue_runtime_ready = lambda mode, rollback=None: None
        settings = self.panel._start_mode("matchzy", restart_if_running=False)
        state = self.panel.read_json(self.panel.ACTIVE_MODE_JSON, {})
        self.assertEqual(state["mode"], "matchzy")
        self.assertEqual(state["settings"], settings)
        self.assertEqual(container.started, 1)
        self.assertEqual(container.restarted, 0)

    def test_start_request_applies_pending_mode_settings(self):
        container = DummyContainer("created")
        self.panel.client = DummyClient(container)
        self.panel.queue_runtime_ready = lambda mode, rollback=None: None
        with mock.patch.object(self.panel.request, "get_json", return_value={"freezetime": 8}):
            response = self.panel.api_mode_start.__wrapped__("heroshift")
        self.assertTrue(response["ok"])
        self.assertEqual(response["settings"]["freezetime"], 8)
        runtime = self.panel.runtime_cfg_path("heroshift").read_text(encoding="utf-8")
        self.assertIn("mp_freezetime 8", runtime)
        self.assertEqual(container.started, 1)

    def test_retakes_config_is_seeded_outside_mode(self):
        settings = self.panel.validate_mode_settings("retakes", {"format": "4v3"})
        changed = self.panel.apply_format_plugin_config("retakes", settings)
        self.assertEqual(changed, "RetakesPlugin.json")
        target = self.panel.mode_config_path("retakes", "RetakesPlugin.json")
        self.assertTrue(target.is_relative_to(self.panel.DATA_DIR / "configs"))

    def test_matchzy_is_locked_to_upstream_defaults(self):
        settings = self.panel.validate_mode_settings(
            "matchzy",
            {
                "format": "1v1",
                "map_pool": ["de_nuke"],
                "hostname": "operator override",
                "freezetime": 1,
            },
        )
        defaults = self.panel.DEFAULT_MODE_SETTINGS["matchzy"]
        self.assertEqual(settings["format"], defaults["format"])
        self.assertEqual(settings["map_pool"], defaults["map_pool"])
        self.assertEqual(settings["hostname"], defaults["hostname"])
        self.assertEqual(settings["freezetime"], defaults["freezetime"])
        runtime = self.panel.generate_runtime_cfg("matchzy", settings, 'sv_password ""')
        commands = [line for line in runtime.splitlines() if line and not line.startswith(("//", "echo", "sv_password"))]
        self.assertEqual(commands, [])
        with self.assertRaisesRegex(PermissionError, "owned by the upstream"):
            self.panel.mode_config_path("matchzy", "MatchZy config.cfg")

    def test_retakes_runtime_does_not_override_plugin_gameplay(self):
        settings = self.panel.validate_mode_settings("retakes", {"format": "4v3"})
        commands = self.panel.hot_convar_lines("retakes", settings)
        self.assertIn("sv_maxplayers 7", commands)
        self.assertTrue(any(line.startswith("hostname ") for line in commands))
        for prefix in ("mp_freezetime ", "mp_warmuptime ", "mp_maxrounds ", "mp_maxmoney ", "bot_quota "):
            self.assertFalse(any(line.startswith(prefix) for line in commands), prefix)

    def test_hero_and_warcraft_keep_panel_gameplay_controls(self):
        for mode in ("heroshift", "warcraft"):
            settings = self.panel.validate_mode_settings(mode, {"freezetime": 7})
            commands = self.panel.hot_convar_lines(mode, settings)
            self.assertIn("mp_freezetime 7", commands)

    def test_post_ready_guard_respects_mode_ownership(self):
        captured = []
        with mock.patch.object(self.panel, "rcon_command", side_effect=lambda _container, command, _timeout: captured.append(command)):
            config_guard.apply_saved_runtime(self.panel, "matchzy")
        self.assertEqual(captured, [])

        with mock.patch.object(self.panel, "rcon_command", side_effect=lambda _container, command, _timeout: captured.append(command)):
            config_guard.apply_saved_runtime(self.panel, "retakes")
        for prefix in ("mp_freezetime ", "mp_warmuptime ", "mp_maxrounds ", "mp_maxmoney ", "bot_quota "):
            self.assertFalse(any(line.startswith(prefix) for line in captured), prefix)


if __name__ == "__main__":
    unittest.main()
