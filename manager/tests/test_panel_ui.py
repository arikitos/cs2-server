from __future__ import annotations

import json
import unittest
from pathlib import Path


MANAGER = Path(__file__).resolve().parents[1]
TEMPLATE = MANAGER / "panel/templates/index.html"
STYLES = MANAGER / "panel/static/style.css"


class PanelUiTests(unittest.TestCase):
    def test_panel_exposes_only_requested_configuration_sections(self) -> None:
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("Identity, security and connection", html)
        self.assertIn("Server hostname", html)
        self.assertIn("Server password", html)
        self.assertIn("Timing and economy", html)
        self.assertIn("Friendly fire", html)
        self.assertIn("MAP POOL", html)
        self.assertNotIn("Lobby visibility and password", html)
        self.assertNotIn("Players and teams", html)
        self.assertNotIn("category('Bots'", html)
        self.assertNotIn("Enable sv_cheats", html)
        self.assertNotIn("Lobby connections only", html)
        self.assertNotIn("friendlyFireForm", html)

    def test_panel_has_exact_server_lifecycle_actions(self) -> None:
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(">Start Server</button>", html)
        self.assertIn(">Stop Server</button>", html)
        self.assertIn(">Reset &amp; Stop</button>", html)
        self.assertNotIn("Save &amp; apply live", html)
        self.assertNotIn("Save &amp; restart", html)
        self.assertNotIn("Reset to defaults", html)

    def test_panel_has_mobile_layout_guards(self) -> None:
        css = STYLES.read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 640px)", css)
        self.assertIn("grid-template-columns: 1fr", css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("minmax(0, 1fr)", css)

    def test_mode_defaults_match_streamlined_panel_contract(self) -> None:
        for path in sorted((MANAGER / "modes").glob("*/mode.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            defaults = manifest["settings"]["defaults"]
            formats = {row["key"]: row for row in manifest["settings"]["formats"]}
            with self.subTest(mode=manifest["id"]):
                self.assertEqual(defaults["round_time"], 1.92)
                self.assertEqual(defaults["bot_quota"], formats[defaults["format"]]["capacity"])
                self.assertEqual(defaults["bot_quota_mode"], "match")
                self.assertEqual(defaults["bot_difficulty"], 3)
                self.assertEqual(defaults["bot_chatter"], "normal")
                self.assertTrue(defaults["bot_join_after_player"])
                self.assertFalse(defaults["auto_team_balance"])

    def test_matchzy_live_round_time_matches_panel_default(self) -> None:
        for name in ("live.cfg", "live_wingman.cfg"):
            text = (MANAGER / "modes/faceit/cfg/MatchZy" / name).read_text(encoding="utf-8")
            self.assertIn("mp_roundtime 1.92", text)
            self.assertIn("mp_roundtime_defuse 1.92", text)
            self.assertIn("mp_roundtime_hostage 1.92", text)

    def test_matchzy_phases_do_not_override_panel_bot_quota(self) -> None:
        matchzy = MANAGER / "modes/faceit/cfg/MatchZy"
        for path in sorted(matchzy.glob("*.cfg")):
            with self.subTest(config=path.name):
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertFalse(any(line.strip().startswith("bot_quota ") for line in lines))


if __name__ == "__main__":
    unittest.main()
