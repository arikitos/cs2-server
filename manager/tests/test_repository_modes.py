from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
REPO_MODES = ROOT / "modes"
sys.path.insert(0, str(RUNTIME))

from mode_applier import apply_mode, verify_mode  # noqa: E402


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class RepositoryModeManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.modes = self.root / "modes"
        self.shared = self.root / "shared"
        self.server = self.root / "server"
        self.absolute = self.root / "absolute"
        self.data = self.root / "data"
        self.versions = self.root / "versions.json"
        self.installed = self.server / "game/csgo/addons/.cs2-manager-versions.json"
        (self.server / "game/csgo").mkdir(parents=True)
        write_json(self.versions, {
            "metamod": {"version": "2.0.0-git1410"},
            "counterstrikesharp": {"version": "1.0.371"},
        })
        write_json(self.installed, {
            "metamod": "2.0.0-git1410",
            "counterstrikesharp": "1.0.371",
        })
        self.manifests = {}
        for source_manifest in REPO_MODES.glob("*/mode.json"):
            mode = source_manifest.parent.name
            manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
            self.manifests[mode] = manifest
            destination = self.modes / mode / "mode.json"
            write_json(destination, manifest)
            cfg = self.modes / mode / "cfg"
            cfg.mkdir(parents=True, exist_ok=True)
            (cfg / manifest["startup"]["mode_cfg"]).write_text("exec server.cfg\n")
            (cfg / manifest["startup"]["runtime_cfg"]).write_text("mp_maxrounds 24\n")

        # Materialize every declared source. Directories first, then files so
        # nested HeroShift configs and gamedata are represented exactly.
        mounts = []
        for mode, manifest in self.manifests.items():
            for plugin in manifest["plugins"]:
                mounts.extend((mode, row) for row in plugin["mounts"])
            mounts.extend((mode, row) for row in manifest.get("configs", []))
        for mode, row in mounts:
            if row.get("kind", "dir") != "dir":
                continue
            root = self.shared if row.get("shared") else self.modes / mode
            path = root.joinpath(*row["source"].split("/"))
            path.mkdir(parents=True, exist_ok=True)
            (path / "fixture.bin").write_text(f"{mode}:{row['target']}")
        for mode, row in mounts:
            if row.get("kind", "dir") != "file":
                continue
            root = self.shared if row.get("shared") else self.modes / mode
            path = root.joinpath(*row["source"].split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{mode}:{row['target']}")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def runtime_settings(self, mode: str) -> dict:
        """Mirror how the panel derives runtime state from the manifest defaults."""
        settings = dict(self.manifests[mode]["settings"]["defaults"])
        formats = {row["key"]: row for row in self.manifests[mode]["settings"]["formats"]}
        chosen = formats[settings["format"]]
        settings["map"] = settings["map_pool"][0]
        settings["capacity"] = chosen["capacity"]
        settings["game_alias"] = chosen.get(
            "game_alias", self.manifests[mode]["startup"]["game_alias"]
        )
        return settings

    def apply(self, mode: str):
        state = self.data / "runtime/active-mode.json"
        write_json(state, {"mode": mode, "settings": self.runtime_settings(mode)})
        return apply_mode(
            state_path=state,
            modes_root=self.modes,
            shared_root=self.shared,
            server_root=self.server,
            inventory_path=self.data / "runtime/managed-files.json",
            env_path=self.data / "runtime/mode.env",
            absolute_root=self.absolute,
            versions_path=self.versions,
            installed_versions_path=self.installed,
        )

    def test_all_repository_manifests_verify(self) -> None:
        for mode in ("faceit", "retake", "heroshift"):
            with self.subTest(mode=mode):
                result = verify_mode(
                    mode=mode,
                    modes_root=self.modes,
                    shared_root=self.shared,
                    server_root=self.server,
                    absolute_root=self.absolute,
                    versions_path=self.versions,
                    installed_versions_path=self.installed,
                )
                self.assertGreater(len(result["entries"]), 0)

    def test_real_manifest_switch_sequence_is_isolated(self) -> None:
        self.apply("faceit")
        self.assertTrue((self.server / "game/csgo/addons/counterstrikesharp/plugins/MatchZy").exists())

        self.apply("heroshift")
        self.assertFalse((self.server / "game/csgo/addons/counterstrikesharp/plugins/MatchZy").exists())
        self.assertTrue((self.server / "game/csgo/addons/counterstrikesharp/gamedata/HeroShift.gamedata.json").is_file())
        self.assertTrue((self.server / "game/csgo/addons/metamod/RayTrace.vdf").is_file())
        self.assertTrue((self.absolute / "addons/RayTrace/gamedata.json").is_file())

        self.apply("retake")
        self.assertFalse((self.server / "game/csgo/addons/counterstrikesharp/plugins/HeroShift").exists())
        self.assertFalse((self.server / "game/csgo/addons/metamod/RayTrace.vdf").exists())
        self.assertFalse((self.absolute / "addons/RayTrace/gamedata.json").exists())
        self.assertTrue((self.server / "game/csgo/addons/counterstrikesharp/plugins/RetakesPlugin").is_dir())
        inventory = json.loads((self.data / "runtime/managed-files.json").read_text())
        self.assertEqual(inventory["mode"], "retake")

    def test_format_alias_reaches_the_launcher_env(self) -> None:
        self.apply("faceit")
        env = (self.data / "runtime/mode.env").read_text(encoding="utf-8")
        self.assertIn("CS2_GAMEALIAS=competitive", env)
        self.assertIn("CS2_MAXPLAYERS=10", env)

        state = self.data / "runtime/active-mode.json"
        settings = self.runtime_settings("faceit")
        settings.update({"format": "2v2", "capacity": 4, "game_alias": "wingman"})
        write_json(state, {"mode": "faceit", "settings": settings})
        apply_mode(
            state_path=state,
            modes_root=self.modes,
            shared_root=self.shared,
            server_root=self.server,
            inventory_path=self.data / "runtime/managed-files.json",
            env_path=self.data / "runtime/mode.env",
            absolute_root=self.absolute,
            versions_path=self.versions,
            installed_versions_path=self.installed,
        )
        env = (self.data / "runtime/mode.env").read_text(encoding="utf-8")
        self.assertIn("CS2_GAMEALIAS=wingman", env)
        self.assertIn("CS2_MAXPLAYERS=4", env)


if __name__ == "__main__":
    unittest.main()
