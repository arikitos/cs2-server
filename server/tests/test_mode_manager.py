from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/runtime"))

import mode_manager  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class ModeManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.modes = self.root / "modes"
        self.server = self.root / "server"
        self.state = self.root / "state"
        self.config = self.root / "server.cfg"
        self.versions = self.root / "versions.json"
        self.installed = self.server / "game/csgo/addons/.cs2-manager-versions.json"
        self.config.write_text("hostname default\n", encoding="utf-8")
        write_json(
            self.versions,
            {
                "metamod": {"version": "2.0.0"},
                "counterstrikesharp": {"version": "1.0.0"},
            },
        )
        write_json(
            self.installed,
            {"metamod": "2.0.0", "counterstrikesharp": "1.0.0"},
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_mode(
        self, name: str, plugin: str, *, with_config: bool = False,
        config_editable: bool = True,
    ) -> None:
        root = self.modes / name
        plugin_dir = root / f"addons/counterstrikesharp/plugins/{plugin}"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / f"{plugin}.dll").write_bytes(name.encode())
        cfg = root / "cfg"
        cfg.mkdir()
        (cfg / f"mode_{name}.cfg").write_text(f"echo {name}\n", encoding="utf-8")
        configs = []
        if with_config:
            target = f"addons/counterstrikesharp/plugins/{plugin}/config.json"
            (plugin_dir / "config.json").write_text('{"value": 1}\n', encoding="utf-8")
            configs.append({
                "name": "config.json",
                "target": target,
                "editable": config_editable,
            })
        write_json(
            root / "mode.json",
            {
                "id": name,
                "startup": {
                    "game_alias": "competitive",
                    "mode_cfg": f"mode_{name}.cfg",
                    "runtime_cfg": "panel_runtime.cfg",
                },
                "plugins": [
                    {
                        "name": plugin,
                        "path": f"addons/counterstrikesharp/plugins/{plugin}",
                    }
                ],
                "configs": configs,
                "requires": {
                    "metamod": "2.0.0",
                    "counterstrikesharp": "1.0.0",
                },
            },
        )
        runtime = self.state / "runtime" / name / "panel_runtime.cfg"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(f"echo runtime-{name}\n", encoding="utf-8")

    def apply(self, mode: str) -> dict:
        state_path = self.state / "runtime/active-mode.json"
        write_json(
            state_path,
            {
                "version": 1,
                "mode": mode,
                "settings": {
                    "capacity": 10,
                    "map": "de_dust2",
                    "game_alias": "competitive",
                },
            },
        )
        return mode_manager.apply_mode(
            modes_root=self.modes,
            server_root=self.server,
            state_root=self.state,
            server_config=self.config,
            versions_path=self.versions,
            installed_versions_path=self.installed,
            state_path=state_path,
            env_path=self.root / "mode.env",
        )

    def test_switch_removes_only_previous_inventory(self) -> None:
        self.make_mode("alpha", "Alpha")
        self.make_mode("beta", "Beta")
        sentinel = self.server / "game/csgo/addons/framework.txt"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("keep", encoding="utf-8")

        self.apply("alpha")
        self.apply("beta")

        self.assertFalse(
            (self.server / "game/csgo/addons/counterstrikesharp/plugins/Alpha/Alpha.dll").exists()
        )
        self.assertTrue(
            (self.server / "game/csgo/addons/counterstrikesharp/plugins/Beta/Beta.dll").is_file()
        )
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_unmanaged_conflict_is_not_overwritten(self) -> None:
        self.make_mode("alpha", "Alpha")
        conflict = self.server / "game/csgo/addons/counterstrikesharp/plugins/Alpha/Alpha.dll"
        conflict.parent.mkdir(parents=True, exist_ok=True)
        conflict.write_bytes(b"operator")

        with self.assertRaisesRegex(mode_manager.ModeError, "unmanaged file"):
            self.apply("alpha")
        self.assertEqual(conflict.read_bytes(), b"operator")

    def test_operator_config_override_and_live_sync(self) -> None:
        self.make_mode("alpha", "Alpha", with_config=True)
        target = "addons/counterstrikesharp/plugins/Alpha/config.json"
        override = self.state / "configs/alpha" / target
        override.parent.mkdir(parents=True)
        override.write_text('{"value": 2}\n', encoding="utf-8")

        self.apply("alpha")
        deployed = self.server / "game/csgo" / target
        self.assertEqual(json.loads(deployed.read_text(encoding="utf-8"))["value"], 2)

        override.write_text('{"value": 3}\n', encoding="utf-8")
        mode_manager.sync_config(
            modes_root=self.modes,
            server_root=self.server,
            state_root=self.state,
            mode="alpha",
            name="config.json",
        )
        self.assertEqual(json.loads(deployed.read_text(encoding="utf-8"))["value"], 3)

    def test_upstream_owned_config_ignores_operator_override(self) -> None:
        self.make_mode("alpha", "Alpha", with_config=True, config_editable=False)
        target = "addons/counterstrikesharp/plugins/Alpha/config.json"
        override = self.state / "configs/alpha" / target
        override.parent.mkdir(parents=True)
        override.write_text('{"value": 99}\n', encoding="utf-8")

        self.apply("alpha")
        deployed = self.server / "game/csgo" / target
        self.assertEqual(json.loads(deployed.read_text(encoding="utf-8"))["value"], 1)
        with self.assertRaisesRegex(mode_manager.ModeError, "owned by the upstream"):
            mode_manager.sync_config(
                modes_root=self.modes,
                server_root=self.server,
                state_root=self.state,
                mode="alpha",
                name="config.json",
            )

    def test_failed_install_restores_previous_mode(self) -> None:
        self.make_mode("alpha", "Alpha")
        self.make_mode("beta", "Beta")
        self.apply("alpha")
        state_path = self.state / "runtime/active-mode.json"
        write_json(
            state_path,
            {"mode": "beta", "settings": {"capacity": 10, "map": "de_dust2"}},
        )
        plan, _ = mode_manager.build_plan(
            self.modes,
            "beta",
            self.state,
            self.config,
            self.versions,
            self.installed,
        )
        real_replace = mode_manager.os.replace
        failed = False

        def fail_beta_install(source, destination):
            nonlocal failed
            if not failed and "staged" in str(source) and str(destination).endswith("Beta.dll"):
                failed = True
                raise OSError("simulated disk failure")
            return real_replace(source, destination)

        with mock.patch.object(mode_manager.os, "replace", side_effect=fail_beta_install):
            with self.assertRaisesRegex(OSError, "simulated"):
                mode_manager.deploy(
                    mode="beta",
                    plan=plan,
                    csgo_root=self.server / "game/csgo",
                    state_root=self.state,
                    inventory_path=self.state / "runtime/mode-inventory.json",
                )

        alpha = self.server / "game/csgo/addons/counterstrikesharp/plugins/Alpha/Alpha.dll"
        beta = self.server / "game/csgo/addons/counterstrikesharp/plugins/Beta/Beta.dll"
        self.assertTrue(alpha.is_file())
        self.assertFalse(beta.exists())
        inventory = json.loads(
            (self.state / "runtime/mode-inventory.json").read_text(encoding="utf-8")
        )
        self.assertEqual(inventory["mode"], "alpha")

    def test_symlink_in_mode_is_rejected(self) -> None:
        self.make_mode("alpha", "Alpha")
        link = self.modes / "alpha/addons/counterstrikesharp/plugins/Alpha/escape.dll"
        try:
            link.symlink_to(self.config)
        except OSError:
            self.skipTest("symlinks are unavailable")
        with self.assertRaisesRegex(mode_manager.ModeError, "Symbolic|symbolic"):
            self.apply("alpha")


if __name__ == "__main__":
    unittest.main()
