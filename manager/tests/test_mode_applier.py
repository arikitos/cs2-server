from __future__ import annotations

import errno
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
sys.path.insert(0, str(RUNTIME))

from mode_applier import ApplyError, apply_mode, cleanup_managed, sync_config  # noqa: E402


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class ModeApplierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.modes = self.root / "modes"
        self.shared = self.root / "shared"
        self.server = self.root / "server"
        self.absolute = self.root / "absolute"
        self.data = self.root / "data"
        self.versions = self.root / "versions.json"
        self.installed_versions = self.server / "game/csgo/addons/.cs2-manager-versions.json"
        (self.server / "game/csgo").mkdir(parents=True)
        (self.shared / "plugins/PanelBridge").mkdir(parents=True)
        (self.shared / "plugins/PanelBridge/bridge.dll").write_text("bridge")
        (self.shared / "cfg").mkdir(parents=True)
        (self.shared / "cfg/server.cfg").write_text("hostname test\n")
        write_json(self.versions, {
            "metamod": {"version": "2.0.0-git1410"},
            "counterstrikesharp": {"version": "1.0.371"},
        })
        write_json(self.installed_versions, {
            "metamod": "2.0.0-git1410",
            "counterstrikesharp": "1.0.371",
        })

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_mode(self, mode: str, plugin: str, *, raytrace: bool = False) -> None:
        root = self.modes / mode
        (root / "cfg").mkdir(parents=True)
        (root / f"cfg/mode_{mode}.cfg").write_text("exec server.cfg\n")
        (root / "cfg/panel_runtime.cfg").write_text("mp_maxrounds 24\n")
        (root / f"plugins/{plugin}").mkdir(parents=True)
        (root / f"plugins/{plugin}/{plugin}.dll").write_text(plugin)
        mounts = [
            {
                "source": f"plugins/{plugin}",
                "target": f"addons/counterstrikesharp/plugins/{plugin}",
            }
        ]
        plugins = [
            {"name": plugin, "role": "plugin", "verify": {"required": True}, "mounts": mounts},
            {
                "name": "PanelBridge",
                "role": "util",
                "verify": {"required": False},
                "mounts": [
                    {
                        "source": "plugins/PanelBridge",
                        "shared": True,
                        "target": "addons/counterstrikesharp/plugins/PanelBridge",
                    }
                ],
            },
        ]
        if raytrace:
            (root / "utils/RayTrace/addons/metamod").mkdir(parents=True)
            (root / "utils/RayTrace/addons/metamod/RayTrace.vdf").write_text("ray")
            (root / "utils/RayTrace/addons/RayTrace").mkdir(parents=True)
            (root / "utils/RayTrace/addons/RayTrace/gamedata.json").write_text("{}")
            plugins.append(
                {
                    "name": "RayTrace",
                    "role": "util",
                    "verify": {"required": True},
                    "mounts": [
                        {
                            "source": "utils/RayTrace/addons/metamod/RayTrace.vdf",
                            "kind": "file",
                            "target": "addons/metamod/RayTrace.vdf",
                        },
                        {
                            "source": "utils/RayTrace/addons/RayTrace/gamedata.json",
                            "kind": "file",
                            "absolute": True,
                            "target": "/addons/RayTrace/gamedata.json",
                        },
                    ],
                }
            )
        manifest = {
            "id": mode,
            "label": mode,
            "implementation": plugin,
            "order": 10,
            "startup": {
                "game_alias": "competitive",
                "mode_cfg": f"mode_{mode}.cfg",
                "runtime_cfg": "panel_runtime.cfg",
            },
            "settings": {
                "capacity": {"min": 1, "max": 10},
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
            "plugins": plugins,
            "configs": [
                {
                    "name": "server.cfg",
                    "source": "cfg/server.cfg",
                    "shared": True,
                    "kind": "file",
                    "target": "cfg/server.cfg",
                }
            ],
            "actions": [],
            "requires": {
                "metamod": "2.0.0-git1410",
                "counterstrikesharp": "1.0.371",
            },
        }
        write_json(root / "mode.json", manifest)

    def apply(self, mode: str) -> dict:
        state = self.data / "runtime/active-mode.json"
        write_json(
            state,
            {
                "mode": mode,
                "settings": {
                    "map": "de_dust2",
                    "capacity": 10,
                    "max_rounds": 24,
                    "freezetime": 15,
                    "friendly_fire": False,
                    "bot_quota": 0,
                },
            },
        )
        return apply_mode(
            state_path=state,
            modes_root=self.modes,
            shared_root=self.shared,
            server_root=self.server,
            inventory_path=self.data / "runtime/managed-files.json",
            env_path=self.data / "runtime/mode.env",
            absolute_root=self.absolute,
            versions_path=self.versions,
            installed_versions_path=self.installed_versions,
        )

    def test_switch_removes_previous_mode_and_preserves_unmanaged_plugin(self) -> None:
        self.make_mode("faceit", "MatchZy")
        self.make_mode("retake", "Retakes")
        unmanaged = self.server / "game/csgo/addons/counterstrikesharp/plugins/AdminTools"
        unmanaged.mkdir(parents=True)
        (unmanaged / "AdminTools.dll").write_text("keep")

        self.apply("faceit")
        self.assertTrue((self.server / "game/csgo/addons/counterstrikesharp/plugins/MatchZy").is_dir())
        self.apply("retake")

        self.assertFalse((self.server / "game/csgo/addons/counterstrikesharp/plugins/MatchZy").exists())
        self.assertTrue((self.server / "game/csgo/addons/counterstrikesharp/plugins/Retakes").is_dir())
        self.assertEqual((unmanaged / "AdminTools.dll").read_text(), "keep")

    def test_raytrace_is_removed_when_leaving_heroshift(self) -> None:
        self.make_mode("heroshift", "HeroShift", raytrace=True)
        self.make_mode("faceit", "MatchZy")
        self.apply("heroshift")
        self.assertTrue((self.server / "game/csgo/addons/metamod/RayTrace.vdf").is_file())
        self.assertTrue((self.absolute / "addons/RayTrace/gamedata.json").is_file())

        self.apply("faceit")
        self.assertFalse((self.server / "game/csgo/addons/metamod/RayTrace.vdf").exists())
        self.assertFalse((self.absolute / "addons/RayTrace/gamedata.json").exists())

    def test_missing_source_fails_before_touching_previous_mode(self) -> None:
        self.make_mode("faceit", "MatchZy")
        self.make_mode("retake", "Retakes")
        self.apply("faceit")
        (self.modes / "retake/plugins/Retakes").rename(self.modes / "retake/plugins/missing")

        with self.assertRaises(ApplyError):
            self.apply("retake")

        self.assertTrue((self.server / "game/csgo/addons/counterstrikesharp/plugins/MatchZy").is_dir())
        inventory = json.loads((self.data / "runtime/managed-files.json").read_text())
        self.assertEqual(inventory["mode"], "faceit")

    def test_overlapping_config_is_carried_by_plugin_directory_once(self) -> None:
        self.make_mode("heroshift", "HeroShift")
        plugin_root = self.modes / "heroshift/plugins/HeroShift"
        (plugin_root / "configs").mkdir()
        (plugin_root / "configs/config.json").write_text("{}")
        manifest_path = self.modes / "heroshift/mode.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["configs"].append(
            {
                "name": "config.json",
                "source": "plugins/HeroShift/configs/config.json",
                "kind": "file",
                "target": "addons/counterstrikesharp/plugins/HeroShift/configs/config.json",
            }
        )
        write_json(manifest_path, manifest)
        result = self.apply("heroshift")
        inventory = json.loads((self.data / "runtime/managed-files.json").read_text())
        targets = [row["target"] for row in inventory["entries"]]
        self.assertIn("addons/counterstrikesharp/plugins/HeroShift", targets)
        self.assertNotIn(
            "addons/counterstrikesharp/plugins/HeroShift/configs/config.json", targets
        )
        self.assertGreater(result["entries"], 0)

    def test_cleanup_removes_only_inventory_owned_paths(self) -> None:
        self.make_mode("heroshift", "HeroShift", raytrace=True)
        self.apply("heroshift")
        unmanaged = self.server / "game/csgo/addons/counterstrikesharp/plugins/External"
        unmanaged.mkdir(parents=True)
        (unmanaged / "External.dll").write_text("external")

        result = cleanup_managed(
            inventory_path=self.data / "runtime/managed-files.json",
            server_root=self.server,
            absolute_root=self.absolute,
        )

        self.assertEqual(result["previous_mode"], "heroshift")
        self.assertTrue((unmanaged / "External.dll").is_file())
        self.assertFalse((self.server / "game/csgo/addons/counterstrikesharp/plugins/HeroShift").exists())
        self.assertFalse((self.absolute / "addons/RayTrace/gamedata.json").exists())
        inventory = json.loads((self.data / "runtime/managed-files.json").read_text())
        self.assertIsNone(inventory["mode"])
        self.assertEqual(inventory["entries"], [])

    def test_sync_config_updates_only_declared_live_file(self) -> None:
        self.make_mode("retake", "Retakes")
        mode_root = self.modes / "retake"
        (mode_root / "config").mkdir()
        (mode_root / "config/Retakes.json").write_text('{"MaxPlayers": 9}')
        manifest_path = mode_root / "mode.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["configs"].append(
            {
                "name": "Retakes.json",
                "source": "config/Retakes.json",
                "kind": "file",
                "target": "addons/counterstrikesharp/configs/plugins/Retakes/Retakes.json",
            }
        )
        write_json(manifest_path, manifest)
        self.apply("retake")
        (mode_root / "config/Retakes.json").write_text('{"MaxPlayers": 8}')

        sync_config(
            mode="retake",
            name="Retakes.json",
            modes_root=self.modes,
            shared_root=self.shared,
            server_root=self.server,
            inventory_path=self.data / "runtime/managed-files.json",
            absolute_root=self.absolute,
            versions_path=self.versions,
            installed_versions_path=self.installed_versions,
        )
        live = self.server / "game/csgo/addons/counterstrikesharp/configs/plugins/Retakes/Retakes.json"
        self.assertEqual(live.read_text(), '{"MaxPlayers": 8}')


    def test_sync_config_rolls_back_when_install_fails(self) -> None:
        self.make_mode("retake", "Retakes")
        mode_root = self.modes / "retake"
        (mode_root / "config").mkdir()
        source = mode_root / "config/Retakes.json"
        source.write_text('{"MaxPlayers": 9}')
        manifest_path = mode_root / "mode.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["configs"].append({
            "name": "Retakes.json",
            "source": "config/Retakes.json",
            "kind": "file",
            "target": "addons/counterstrikesharp/configs/plugins/Retakes/Retakes.json",
        })
        write_json(manifest_path, manifest)
        self.apply("retake")
        live = self.server / "game/csgo/addons/counterstrikesharp/configs/plugins/Retakes/Retakes.json"
        self.assertEqual(live.read_text(), '{"MaxPlayers": 9}')
        source.write_text('{"MaxPlayers": 8}')

        original_rename = Path.rename

        def fail_staged(path: Path, target: Path):
            if path.name == "staged":
                raise OSError("simulated install failure")
            return original_rename(path, target)

        with patch("pathlib.Path.rename", autospec=True, side_effect=fail_staged):
            with self.assertRaises(ApplyError):
                sync_config(
                    mode="retake",
                    name="Retakes.json",
                    modes_root=self.modes,
                    shared_root=self.shared,
                    server_root=self.server,
                    inventory_path=self.data / "runtime/managed-files.json",
                    absolute_root=self.absolute,
                    versions_path=self.versions,
                    installed_versions_path=self.installed_versions,
                )
        self.assertEqual(live.read_text(), '{"MaxPlayers": 9}')

    def test_sync_config_rejects_symlink_source(self) -> None:
        self.make_mode("retake", "Retakes")
        mode_root = self.modes / "retake"
        (mode_root / "config").mkdir()
        source = mode_root / "config/Retakes.json"
        source.write_text('{}')
        manifest_path = mode_root / "mode.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["configs"].append({
            "name": "Retakes.json",
            "source": "config/Retakes.json",
            "kind": "file",
            "target": "addons/counterstrikesharp/configs/plugins/Retakes/Retakes.json",
        })
        write_json(manifest_path, manifest)
        self.apply("retake")
        outside = self.root / "outside.json"
        outside.write_text('{"unsafe": true}')
        source.unlink()
        try:
            source.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.assertRaises(ApplyError):
            sync_config(
                mode="retake",
                name="Retakes.json",
                modes_root=self.modes,
                shared_root=self.shared,
                server_root=self.server,
                inventory_path=self.data / "runtime/managed-files.json",
                absolute_root=self.absolute,
                versions_path=self.versions,
                installed_versions_path=self.installed_versions,
            )

    def test_version_mismatch_fails_before_touching_previous_mode(self) -> None:
        self.make_mode("faceit", "MatchZy")
        self.apply("faceit")
        versions = json.loads(self.versions.read_text())
        versions["counterstrikesharp"]["version"] = "1.0.999"
        write_json(self.versions, versions)

        with self.assertRaises(ApplyError):
            self.apply("faceit")

        inventory = json.loads((self.data / "runtime/managed-files.json").read_text())
        self.assertEqual(inventory["mode"], "faceit")


    def test_installed_version_mismatch_is_rejected(self) -> None:
        self.make_mode("faceit", "MatchZy")
        write_json(self.installed_versions, {
            "metamod": "2.0.0-git1410",
            "counterstrikesharp": "1.0.999",
        })
        with self.assertRaises(ApplyError):
            self.apply("faceit")

    def test_reserved_framework_root_is_rejected(self) -> None:
        self.make_mode("faceit", "MatchZy")
        manifest_path = self.modes / "faceit/mode.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["plugins"][0]["mounts"][0]["target"] = "addons/counterstrikesharp/plugins"
        write_json(manifest_path, manifest)
        with self.assertRaises(ApplyError):
            self.apply("faceit")

    def test_sync_config_rejects_target_added_after_deployment(self) -> None:
        self.make_mode("retake", "Retakes")
        self.apply("retake")
        mode_root = self.modes / "retake"
        (mode_root / "config").mkdir()
        (mode_root / "config/New.json").write_text("{}")
        manifest_path = mode_root / "mode.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["configs"].append({
            "name": "New.json",
            "source": "config/New.json",
            "kind": "file",
            "target": "addons/counterstrikesharp/configs/plugins/New/New.json",
        })
        write_json(manifest_path, manifest)
        with self.assertRaises(ApplyError):
            sync_config(
                mode="retake",
                name="New.json",
                modes_root=self.modes,
                shared_root=self.shared,
                server_root=self.server,
                inventory_path=self.data / "runtime/managed-files.json",
                absolute_root=self.absolute,
                versions_path=self.versions,
                installed_versions_path=self.installed_versions,
            )

    def test_first_deployment_adopts_exact_legacy_target_with_rollback_safety(self) -> None:
        self.make_mode("faceit", "MatchZy")
        legacy = self.server / "game/csgo/addons/counterstrikesharp/plugins/MatchZy"
        legacy.mkdir(parents=True)
        (legacy / "legacy.dll").write_text("legacy")
        self.apply("faceit")
        self.assertFalse((legacy / "legacy.dll").exists())
        self.assertTrue((legacy / "MatchZy.dll").exists())


    def test_symlink_inside_mode_source_is_rejected(self) -> None:
        self.make_mode("faceit", "MatchZy")
        outside = self.root / "outside.dll"
        outside.write_text("outside")
        link = self.modes / "faceit/plugins/MatchZy/escape.dll"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.assertRaises(ApplyError):
            self.apply("faceit")

    def test_cross_device_absolute_target_supports_apply_and_switch(
        self,
    ) -> None:
        self.make_mode("heroshift", "HeroShift", raytrace=True)
        self.make_mode("faceit", "MatchZy")

        absolute_target = (
            self.absolute / "addons/RayTrace/gamedata.json"
        )
        absolute_target.parent.mkdir(parents=True)
        absolute_target.write_text("legacy")

        original_rename = Path.rename

        def simulate_cross_device(path: Path, target: Path):
            source = Path(path)
            destination = Path(target)

            source_is_absolute = (
                source == self.absolute
                or self.absolute in source.parents
            )
            destination_is_absolute = (
                destination == self.absolute
                or self.absolute in destination.parents
            )

            if source_is_absolute != destination_is_absolute:
                raise OSError(
                    errno.EXDEV,
                    "Invalid cross-device link",
                )

            return original_rename(path, target)

        with patch(
            "pathlib.Path.rename",
            autospec=True,
            side_effect=simulate_cross_device,
        ):
            self.apply("heroshift")
            self.assertEqual(
                absolute_target.read_text(),
                "{}",
            )

            self.apply("faceit")

        self.assertFalse(absolute_target.exists())

        inventory = json.loads(
            (
                self.data
                / "runtime/managed-files.json"
            ).read_text()
        )
        self.assertEqual(inventory["mode"], "faceit")


if __name__ == "__main__":
    unittest.main()
