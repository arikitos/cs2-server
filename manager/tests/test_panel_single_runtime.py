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
        (project / "shared/frameworks").mkdir(parents=True, exist_ok=True)
        (project / "shared/frameworks/versions.json").write_text(
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

    def test_hostname_and_economy_validation_reject_unsafe_values(self):
        with self.assertRaises(ValueError):
            self.app.validate_mode_settings("faceit", {"hostname": 'server"; quit'})
        with self.assertRaises(ValueError):
            self.app.validate_mode_settings("faceit", {"start_money": 16000, "max_money": 800})

    def test_expected_api_routes_remain_registered(self):
        rules = {rule for rule, _methods, _name in self.app.app.routes}
        expected = {
            "/api/v3/status",
            "/api/v3/modes/switch",
            "/api/v3/server/start",
            "/api/v3/server/stop",
            "/api/v3/server/restart",
            "/api/v3/server/map",
            "/api/v3/server/visibility",
            "/api/v3/commands",
            "/api/v3/modes/heroshift/diag",
            "/api/v3/maintenance/verify-mounts",
        }
        self.assertTrue(expected.issubset(rules))

    def test_heroshift_reload_action_syncs_new_config_before_rcon(self):
        events = []
        self.app.request.get_json = lambda silent=True: {"action": "reload_skills"}
        self.app.active_container = lambda: {"mode": "heroshift"}
        self.app.sync_live_config = lambda mode, name: events.append(
            ("sync", mode, name)
        )
        self.app.rcon_command = lambda container, command, timeout: events.append(
            ("rcon", container, command, timeout)
        ) or "ok"

        response = self.app.api_mode_action.__wrapped__("heroshift")

        self.assertTrue(response["ok"])
        self.assertEqual(
            events,
            [
                ("sync", "heroshift", "heroshift.json"),
                ("rcon", "cs2-game", "css_reload", 6),
            ],
        )

    def test_panel_hides_container_maintenance_and_embeds_game_logs(self):
        text = (PANEL / "templates/index.html").read_text(encoding="utf-8")
        self.assertNotIn("MAINTENANCE · OWNER", text)
        self.assertNotIn('id="logSource"', text)
        self.assertIn("CS2 GAME LOGS", text)
        self.assertIn("source=container%3Acs2-game", text)
        self.assertIn("sendConsole();", text)

    def test_format_drives_capacity_alias_and_start_map(self):
        settings = self.app.validate_mode_settings("faceit", {
            "format": "2v2",
            "map_pool": ["de_nuke", "de_mirage", "de_nuke"],
        })
        self.assertEqual(settings["capacity"], 4)
        self.assertEqual(settings["game_alias"], "wingman")
        self.assertEqual(settings["map"], "de_nuke")
        # The pool is de-duplicated while keeping the operator's order.
        self.assertEqual(settings["map_pool"], ["de_nuke", "de_mirage"])

        five = self.app.validate_mode_settings("faceit", {"format": "5v5"})
        self.assertEqual((five["capacity"], five["game_alias"]), (10, "competitive"))

    def test_retake_formats_expose_only_the_declared_pair(self):
        self.assertEqual(set(self.app.MODE_FORMATS["retake"]), {"5v4", "4v3"})
        self.assertEqual(
            self.app.validate_mode_settings("retake", {"format": "4v3"})["capacity"], 7
        )
        with self.assertRaises(ValueError):
            self.app.validate_mode_settings("retake", {"format": "5v5"})

    def test_derived_fields_cannot_be_forced_by_a_client(self):
        settings = self.app.validate_mode_settings("faceit", {
            "format": "1v1",
            "map_pool": ["de_mirage"],
            "capacity": 64,
            "map": "de_dust2",
            "game_alias": "deathmatch",
        })
        self.assertEqual(settings["capacity"], 2)
        self.assertEqual(settings["map"], "de_mirage")
        self.assertEqual(settings["game_alias"], "competitive")

    def test_map_pool_rejects_maps_outside_the_allowlist(self):
        with self.assertRaises(ValueError):
            self.app.validate_mode_settings("faceit", {"map_pool": ["de_dust2", "de_evil"]})
        with self.assertRaises(ValueError):
            self.app.validate_mode_settings("faceit", {"map_pool": []})

    def test_legacy_boolean_friendly_fire_is_migrated(self):
        self.assertEqual(
            self.app.validate_mode_settings("faceit", {"friendly_fire": True})["friendly_fire"],
            "regular",
        )
        self.assertEqual(
            self.app.validate_mode_settings("faceit", {"friendly_fire": False})["friendly_fire"],
            "off",
        )
        with self.assertRaises(ValueError):
            self.app.validate_mode_settings("faceit", {"friendly_fire": "sometimes"})

    def test_nades_only_friendly_fire_zeroes_bullet_scaling(self):
        lines = self.app.hot_convar_lines(
            self.app.validate_mode_settings("faceit", {"friendly_fire": "nades"})
        )
        self.assertIn("mp_friendlyfire 1", lines)
        self.assertIn("ff_damage_reduction_bullets 0", lines)
        self.assertIn("ff_damage_reduction_grenade 0.25", lines)
        off = self.app.hot_convar_lines(
            self.app.validate_mode_settings("faceit", {"friendly_fire": "off"})
        )
        self.assertIn("mp_friendlyfire 0", off)
        self.assertIn("ff_damage_reduction_bullets 0.33", off)

    def test_common_settings_reach_the_generated_runtime_cfg(self):
        settings = self.app.validate_mode_settings("faceit", {
            "format": "2v2",
            "freezetime": 9,
            "warmup_time": 45,
            "max_rounds": 16,
            "round_time": 1.5,
            "hostname": "Practice Server",
            "buy_time": 25,
            "c4_timer": 35,
            "start_money": 1000,
            "max_money": 12000,
            "bot_quota": 3,
            "bot_quota_mode": "match",
            "bot_difficulty": 2,
            "overtime": True,
            "overtime_max_rounds": 4,
        })
        text = self.app.generate_runtime_cfg("faceit", settings, 'sv_password ""')
        for expected in (
            "mp_freezetime 9", "mp_warmuptime 45", "mp_maxrounds 16",
            "mp_roundtime 1.5", "bot_quota 4", "mp_overtime_enable 1",
            'hostname "Practice Server"', "bot_quota_mode match", "bot_difficulty 3",
            "bot_chatter normal", "bot_join_after_player 1", "mp_autoteambalance 0",
            "mp_buytime 25", "mp_c4timer 35", "mp_startmoney 1000", "mp_maxmoney 12000",
            "mp_overtime_maxrounds 4",
            "matchzy_minimum_ready_required 4",  # comes from the 2v2 format
            "matchzy_autostart_mode 1",          # comes from the mode extra_cfg
        ):
            self.assertIn(expected, text)

    def test_hidden_server_settings_are_enforced_from_match_format(self):
        settings = self.app.validate_mode_settings("faceit", {
            "format": "1v1",
            "lan": True,
            "cheats": True,
            "allow_lobby_connect_only": True,
            "limit_teams": 5,
            "auto_team_balance": True,
            "spectators_max": 64,
            "bot_quota": 1,
            "bot_quota_mode": "match",
            "bot_difficulty": 0,
            "bot_chatter": "off",
            "bot_join_after_player": False,
            "ff_bullet_reduction": 1,
            "ff_grenade_reduction": 1,
            "ff_other_reduction": 1,
            "tk_punish": True,
        })
        self.assertEqual(settings["capacity"], 2)
        self.assertEqual(settings["bot_quota"], 2)
        self.assertEqual(settings["bot_quota_mode"], "match")
        self.assertEqual(settings["bot_difficulty"], 3)
        self.assertEqual(settings["bot_chatter"], "normal")
        self.assertTrue(settings["bot_join_after_player"])
        self.assertFalse(settings["lan"])
        self.assertFalse(settings["cheats"])
        self.assertFalse(settings["allow_lobby_connect_only"])
        self.assertEqual(settings["limit_teams"], 0)
        self.assertFalse(settings["auto_team_balance"])
        self.assertEqual(settings["spectators_max"], 2)
        self.assertEqual(settings["ff_bullet_reduction"], 0.33)
        self.assertEqual(settings["ff_grenade_reduction"], 0.25)
        self.assertEqual(settings["ff_other_reduction"], 0.4)
        self.assertFalse(settings["tk_punish"])

    def test_format_writes_the_retake_plugin_config(self):
        path = self.app.mode_config_path("retake", "RetakesPlugin.json")
        self.app.apply_format_plugin_config(
            "retake", self.app.validate_mode_settings("retake", {"format": "5v4"})
        )
        changed = self.app.apply_format_plugin_config(
            "retake", self.app.validate_mode_settings("retake", {"format": "4v3"})
        )
        self.assertEqual(changed, "RetakesPlugin.json")
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["GameSettings"]["MaxPlayers"], 7)
        self.assertEqual(document["TeamSettings"]["TerroristRatio"], 0.43)
        # A second identical apply is a no-op, so no needless backup churn.
        self.assertIsNone(self.app.apply_format_plugin_config(
            "retake", self.app.validate_mode_settings("retake", {"format": "4v3"})
        ))

    def test_command_catalog_prefers_plugin_match_controls(self):
        settings = self.app.validate_mode_settings("faceit", {"format": "2v2"})
        commands = {
            command["cmd"]
            for group in self.app.command_catalog("faceit", settings)
            for command in group["commands"]
        }
        self.assertIn("css_pause", commands)
        self.assertIn("css_unpause", commands)
        self.assertNotIn("mp_pause_match", commands)
        self.assertNotIn("mp_unpause_match", commands)

    def test_command_catalog_exposes_bot_add_and_plugin_commands(self):
        settings = self.app.validate_mode_settings("retake", {})
        commands = {
            command["cmd"]
            for group in self.app.command_catalog("retake", settings)
            for command in group["commands"]
        }
        self.assertIn("bot_add", commands)
        self.assertIn("bot_kick", commands)
        self.assertIn("bot_kill", commands)
        self.assertIn("banid", commands)
        self.assertIn("mp_buy_anywhere", commands)
        self.assertIn("css_forcebombsite A", commands)
        self.assertIn("status", commands)

    def test_console_catalog_allows_only_declared_commands(self):
        settings = self.app.validate_mode_settings("retake", {})
        self.assertTrue(self.app.catalog_allows_command("retake", settings, "bot_add"))
        self.assertTrue(self.app.catalog_allows_command("retake", settings, "banid 0 STEAM_1:0:1"))
        self.assertFalse(self.app.catalog_allows_command("retake", settings, "exec server.cfg"))
        self.assertFalse(self.app.catalog_allows_command("retake", settings, "sv_cheats 1"))

    def test_status_payload_carries_everything_the_panel_ui_reads(self):
        self.app.client = DummyClient(DummyContainer("exited"))
        # api_status is behind require_auth, so present the configured credentials.
        self.app.request.authorization = types.SimpleNamespace(
            username=self.app.USERNAME, password=self.app.PASSWORD
        )
        self.addCleanup(setattr, self.app.request, "authorization", None)
        payload = self.app.api_status()
        self.assertEqual(payload["visibility"], "public")
        self.assertIn("has_password", payload["password"])
        self.assertEqual(payload["friendly_fire_modes"], ["off", "nades", "regular"])
        self.assertEqual(
            payload["apply_levels"]["format"], "game_restart",
        )
        for mode in payload["mode_order"]:
            with self.subTest(mode=mode):
                formats = payload["mode_meta"][mode]["formats"]
                self.assertTrue(formats)
                for entry in formats:
                    self.assertEqual(
                        set(entry), {"key", "label", "detail", "capacity", "team_size", "game_alias"},
                    )
                for field in self.app.mode_defs.SETTING_FIELDS:
                    self.assertIn(field, payload["modes"][mode])
                    self.assertIn(field, payload["mode_defaults"][mode])

    def test_stored_legacy_settings_are_upgraded_in_place(self):
        legacy = {"map": "de_nuke", "capacity": 10, "max_rounds": 30, "friendly_fire": True}
        self.app.save_mode("faceit", legacy)
        settings = self.app.validate_mode_settings("faceit", self.app.load_mode("faceit"))
        self.assertEqual(settings["format"], "5v5")
        self.assertEqual(settings["friendly_fire"], "regular")
        self.assertEqual(settings["max_rounds"], 30)
        self.assertNotIn("legacy", settings)
        # 'map' is derived from the pool, not carried over from the stale key.
        self.assertEqual(settings["map"], settings["map_pool"][0])


if __name__ == "__main__":
    unittest.main()
