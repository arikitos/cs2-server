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
        "capacity": {"min": 2, "max": 10},
        "defaults": {
            "map": "de_dust2",
            "capacity": 10,
            "max_rounds": 24,
            "freezetime": 15,
            "friendly_fire": False,
            "bot_quota": 0,
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
