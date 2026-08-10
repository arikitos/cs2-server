from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parents[1] / "panel"
sys.path.insert(0, str(PANEL))

from mode_defs import DefinitionError, load_definitions, parse_definition  # noqa: E402


BASE = {
    "id": "faceit",
    "label": "FaceIt",
    "implementation": "MatchZy",
    "order": 10,
    "requires": {"metamod": "2.0.0-git1410", "counterstrikesharp": "1.0.371"},
    "startup": {
        "game_alias": "competitive",
        "mode_cfg": "mode_faceit.cfg",
        "runtime_cfg": "panel_runtime.cfg",
    },
    "settings": {
        "formats": [
            {
                "key": "5v5",
                "label": "5v5",
                "capacity": 10,
                "team_size": 5,
                "default": True,
            },
            {
                "key": "2v2",
                "label": "2v2",
                "capacity": 4,
                "team_size": 2,
                "game_alias": "wingman",
            },
        ],
        "defaults": {
            "format": "5v5",
            "map_pool": ["de_dust2", "de_mirage"],
            "hostname": "FaceIt Server",
            "lan": False,
            "cheats": False,
            "allow_lobby_connect_only": False,
            "limit_teams": 0,
            "auto_team_balance": False,
            "spectators_max": 2,
            "max_rounds": 24,
            "freezetime": 15,
            "warmup_time": 60,
            "round_time": 1.55,
            "buy_time": 20,
            "c4_timer": 40,
            "start_money": 800,
            "max_money": 16000,
            "friendly_fire": "off",
            "bot_quota": 0,
            "bot_quota_mode": "match",
            "bot_difficulty": 1,
            "bot_chatter": "off",
            "bot_join_after_player": True,
            "ff_bullet_reduction": 0.33,
            "ff_grenade_reduction": 0.25,
            "ff_other_reduction": 0.4,
            "tk_punish": False,
            "overtime": True,
            "overtime_max_rounds": 6,
        },
        "extra_cfg": [],
    },
    "plugins": [
        {
            "name": "MatchZy",
            "role": "plugin",
            "verify": {"required": True, "aliases": ["matchzy"]},
            "mounts": [
                {
                    "source": "plugins/MatchZy",
                    "target": "addons/counterstrikesharp/plugins/MatchZy",
                }
            ],
        }
    ],
    "configs": [],
    "actions": [],
}


class ModeDefinitionTests(unittest.TestCase):
    def test_container_fields_are_rejected(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["container"] = "cs2-faceit"
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_requires_are_normalized(self) -> None:
        parsed = parse_definition(BASE, "faceit")
        self.assertEqual(parsed["requires"]["counterstrikesharp"], "1.0.371")
        self.assertNotIn("container", parsed)

    def test_absolute_targets_are_restricted(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["plugins"][0]["mounts"][0] = {
            "source": "plugins/MatchZy",
            "target": "/etc/passwd",
            "absolute": True,
        }
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_optional_mount_is_normalized_and_must_be_boolean(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["plugins"][0]["mounts"][0]["optional"] = True
        parsed = parse_definition(raw, "faceit")
        self.assertTrue(parsed["plugins"][0]["mounts"][0]["optional"])

        raw["plugins"][0]["mounts"][0]["optional"] = "yes"
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_requires_are_mandatory(self) -> None:
        raw = json.loads(json.dumps(BASE))
        del raw["requires"]["metamod"]
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_reserved_framework_root_is_rejected_early(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["plugins"][0]["mounts"][0]["target"] = "addons/counterstrikesharp/plugins"
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_empty_target_segment_is_rejected(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["plugins"][0]["mounts"][0]["target"] = "addons//MatchZy"
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_capacity_range_is_derived_from_formats(self) -> None:
        parsed = parse_definition(BASE, "faceit")
        self.assertEqual(parsed["capacity"], {"min": 4, "max": 10})
        self.assertEqual([entry["key"] for entry in parsed["formats"]], ["5v5", "2v2"])

    def test_format_inherits_startup_alias_and_may_override_it(self) -> None:
        parsed = parse_definition(BASE, "faceit")
        aliases = {entry["key"]: entry["game_alias"] for entry in parsed["formats"]}
        self.assertEqual(aliases, {"5v5": "competitive", "2v2": "wingman"})

    def test_default_format_must_be_declared(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["settings"]["defaults"]["format"] = "3v3"
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_duplicate_format_keys_are_rejected(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["settings"]["formats"][1]["key"] = "5v5"
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_empty_map_pool_is_rejected(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["settings"]["defaults"]["map_pool"] = []
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_friendly_fire_must_be_a_known_mode(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["settings"]["defaults"]["friendly_fire"] = True
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_hostname_and_bot_modes_are_validated(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["settings"]["defaults"]["hostname"] = 'server"; quit'
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")
        raw = json.loads(json.dumps(BASE))
        raw["settings"]["defaults"]["bot_quota_mode"] = "unbounded"
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_format_plugin_config_must_target_a_declared_config(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["settings"]["formats"][0]["plugin_config"] = {
            "config": "Unknown.json",
            "set": {"GameSettings.MaxPlayers": 10},
        }
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_format_plugin_config_rejects_unsafe_paths(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["configs"] = [{
            "name": "Plugin.json",
            "source": "config/Plugin.json",
            "kind": "file",
            "target": "addons/counterstrikesharp/configs/plugins/X/Plugin.json",
        }]
        raw["settings"]["formats"][0]["plugin_config"] = {
            "config": "Plugin.json",
            "set": {"../escape": 1},
        }
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_format_cfg_rejects_command_chaining(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["settings"]["formats"][0]["cfg"] = ["mp_maxrounds 16; quit"]
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_action_group_is_validated_and_defaulted(self) -> None:
        raw = json.loads(json.dumps(BASE))
        raw["actions"] = [{
            "key": "start", "label": "Start", "cmd": "css_start",
            "impact": "Match", "description": "Starts.",
        }]
        self.assertEqual(parse_definition(raw, "faceit")["actions"][0]["group"], "match")
        raw["actions"][0]["group"] = "nonsense"
        with self.assertRaises(DefinitionError):
            parse_definition(raw, "faceit")

    def test_load_definitions_does_not_require_unique_containers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for mode, order in (("faceit", 10), ("retake", 20)):
                raw = json.loads(json.dumps(BASE))
                raw["id"] = mode
                raw["label"] = mode
                raw["order"] = order
                raw["startup"]["mode_cfg"] = f"mode_{mode}.cfg"
                path = root / mode
                path.mkdir()
                (path / "mode.json").write_text(json.dumps(raw), encoding="utf-8")
            definitions, errors = load_definitions(root)
            self.assertEqual(errors, [])
            self.assertEqual(list(definitions), ["faceit", "retake"])


if __name__ == "__main__":
    unittest.main()
