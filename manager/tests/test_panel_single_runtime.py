import importlib.util
import json
import logging
import os
import sys
import tempfile
import shutil
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "panel"
MODES = ROOT / "modes"
sys.path.insert(0, str(PANEL))


class DummyFlask:
    def __init__(self, *_args, **_kwargs):
        self.logger = logging.getLogger("panel-test")
        self.routes = []

    def _decorator(self, rule, methods):
        def register(fn):
            self.routes.append((rule, tuple(methods), fn.__name__))
            return fn
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

    def __bool__(self):
        return False


class DummyContainer:
    def __init__(self, status="created"):
        self.status = status
        self.attrs = {"State": {"StartedAt": None}, "RestartCount": 0}
        self.started = 0
        self.restarted = 0
        self.stopped = 0

    def reload(self):
        return None

    def start(self):
        self.started += 1
        self.status = "running"

    def restart(self, timeout=20):
        self.restarted += 1
        self.status = "running"

    def stop(self, timeout=20):
        self.stopped += 1
        self.status = "exited"


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


class PanelSingleRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        project = root / "project"
        project.mkdir()
        temp_modes = root / "modes"
        shutil.copytree(MODES, temp_modes, ignore=shutil.ignore_patterns("panel_runtime.cfg"))
        (project / "versions.json").write_text(
            json.dumps({
                "metamod": {"version": "2.0.0-git1410"},
                "counterstrikesharp": {"version": "1.0.371"},
            }),
            encoding="utf-8",
        )
        os.environ.update({
            "PANEL_DATA_DIR": str(root / "data"),
            "PANEL_MODES_DIR": str(temp_modes),
            "PANEL_PROJECT_DIR": str(project),
            "PANEL_SERVER_DIR": str(root / "server"),
            "GAME_CONTAINER": "cs2-game",
        })

        flask = types.ModuleType("flask")
        flask.Flask = DummyFlask
        flask.Response = lambda *a, **k: (a, k)
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
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)

    def tearDown(self):
        self.temp.cleanup()
        sys.modules.pop("panel_app_test", None)

    def test_all_modes_use_one_container(self):
        self.assertEqual(self.app.GAME_CONTAINERS, ["cs2-game"])
        self.assertEqual({row["container"] for row in self.app.MODES.values()}, {"cs2-game"})

    def test_start_writes_state_and_starts_single_container(self):
        container = DummyContainer("created")
        self.app.client = DummyClient(container)
        self.app.queue_runtime_ready = lambda mode, rollback=None: None
        settings = self.app._start_mode("faceit", restart_if_running=False)
        state = json.loads(self.app.ACTIVE_MODE_JSON.read_text(encoding="utf-8"))
        self.assertEqual(state["mode"], "faceit")
        self.assertEqual(state["settings"], settings)
        self.assertEqual(container.started, 1)
        self.assertEqual(container.restarted, 0)

    def test_switch_restarts_same_container(self):
        container = DummyContainer("running")
        self.app.client = DummyClient(container)
        self.app.queue_runtime_ready = lambda mode, rollback=None: None
        self.app._start_mode("retake", restart_if_running=True)
        self.assertEqual(container.restarted, 1)
        self.assertEqual(container.started, 0)
        self.assertEqual(self.app.selected_runtime_mode(), "retake")

    def test_switch_passes_previous_mode_as_readiness_rollback(self):
        first = DummyContainer("created")
        self.app.client = DummyClient(first)
        self.app.queue_runtime_ready = lambda mode, rollback=None: None
        self.app._start_mode("faceit", restart_if_running=False)

        running = DummyContainer("running")
        self.app.client = DummyClient(running)
        captured = {}
        self.app.queue_runtime_ready = lambda mode, rollback=None: captured.update(
            {"mode": mode, "rollback": rollback}
        )
        self.app._start_mode("retake", restart_if_running=True)
        self.assertEqual(captured["mode"], "retake")
        self.assertEqual(captured["rollback"][0], "faceit")
        self.assertEqual(captured["rollback"][1]["capacity"], 10)

    def test_docker_restart_failure_restores_previous_state(self):
        first = DummyContainer("created")
        self.app.client = DummyClient(first)
        self.app.queue_runtime_ready = lambda mode, rollback=None: None
        self.app._start_mode("faceit", restart_if_running=False)

        app_module = self.app
        class FailingContainer(DummyContainer):
            def restart(self, timeout=20):
                raise app_module.DockerException("restart failed")
        failing = FailingContainer("running")
        self.app.client = DummyClient(failing)
        with self.assertRaises(self.app.DockerException):
            self.app._start_mode("retake", restart_if_running=True)
        state = json.loads(self.app.ACTIVE_MODE_JSON.read_text(encoding="utf-8"))
        self.assertEqual(state["mode"], "faceit")
        self.assertEqual(self.app.load_server()["last_mode"], "faceit")

    def test_console_command_rejects_command_chaining(self):
        with self.assertRaises(ValueError):
            self.app.validate_console_command("status; quit")
        self.assertEqual(self.app.validate_console_command("status"), "status")

    def test_server_password_rejects_cfg_injection(self):
        for value in ('abc"; quit', "abc;quit", "abc\nquit", "abc\\quit"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.app.validate_server_password(value)
        self.assertEqual(self.app.validate_server_password("safe password"), "safe password")

    def test_expected_api_routes_remain_registered(self):
        rules = {rule for rule, _methods, _name in self.app.app.routes}
        expected = {
            "/api/v3/status",
            "/api/v3/modes/switch",
            "/api/v3/server/start",
            "/api/v3/server/stop",
            "/api/v3/server/restart",
            "/api/v3/modes/heroshift/skills",
            "/api/v3/maintenance/verify-mounts",
        }
        self.assertTrue(expected.issubset(rules))


if __name__ == "__main__":
    unittest.main()
