from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

MANAGER = Path(__file__).resolve().parents[1]
PANEL = MANAGER / "panel"
sys.path.insert(0, str(PANEL))

from mode_defs import parse_definition  # noqa: E402


class SuperHeroModeTests(unittest.TestCase):
    def test_superhero_mode_definition_is_valid(self) -> None:
        mode_root = MANAGER / "modes" / "superhero"
        raw = json.loads((mode_root / "mode.json").read_text(encoding="utf-8"))
        parsed = parse_definition(raw, "superhero")
        self.assertEqual(parsed["id"], "superhero")
        self.assertEqual(parsed["requires"]["counterstrikesharp"], "1.0.371")
        self.assertEqual(parsed["capacity"], {"min": 2, "max": 10})
        self.assertIn("SuperHeroMod", parsed["required_plugins"])

    def test_superhero_catalog_has_25_unique_heroes(self) -> None:
        heroes = json.loads((MANAGER / "modes" / "superhero" / "config" / "heroes.json").read_text(encoding="utf-8"))
        self.assertEqual(len(heroes), 25)
        ids = [hero["Id"] for hero in heroes]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_runtime_sources_exist(self) -> None:
        mode_root = MANAGER / "modes" / "superhero"
        required = [
            mode_root / "cfg" / "mode_superhero.cfg",
            mode_root / "cfg" / "panel_runtime.cfg",
            mode_root / "config" / "SuperHeroMod.json",
            mode_root / "config" / "heroes.json",
            mode_root / "src" / "SuperHeroMod" / "SuperHeroMod.csproj",
        ]
        self.assertTrue(all(path.is_file() for path in required))


if __name__ == "__main__":
    unittest.main()
