from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "panel"))
sys.path.insert(0, str(ROOT / "server/runtime"))

import mode_defs  # noqa: E402
import mode_manager  # noqa: E402


class RepositoryContractTests(unittest.TestCase):
    def test_runtime_layout_is_direct(self) -> None:
        for name in ("panel", "modes", "server"):
            self.assertTrue((ROOT / name).is_dir(), name)
        self.assertTrue((ROOT / "install-windows.cmd").is_file())
        self.assertTrue((ROOT / "setup-on-windows.ps1").is_file())
        self.assertFalse((ROOT / "setup.ps1").exists())
        self.assertFalse((ROOT / "manager").exists())
        self.assertFalse((ROOT / "installs").exists())

    def test_windows_installer_contract(self) -> None:
        launcher = (ROOT / "install-windows.cmd").read_text(encoding="utf-8")
        setup = (ROOT / "setup-on-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("powershell.exe", launcher)
        self.assertIn("setup-on-windows.ps1", launcher)
        self.assertIn('$env:OS -ne "Windows_NT"', setup)
        self.assertIn('Docker/Docker/Docker Desktop.exe', setup)
        self.assertIn('$dockerOs -ne "linux"', setup)
        self.assertIn('@("amd64", "x86_64")', setup)
        self.assertIn('"server/cs2"', setup)
        self.assertIn('New-Object System.Text.UTF8Encoding($false)', setup)

    def test_runtime_has_no_arm_emulation_path(self) -> None:
        launcher = (ROOT / "server/runtime/runtime-launcher.sh").read_text(encoding="utf-8")
        self.assertIn("exec ./cs2.sh -dedicated", launcher)
        self.assertNotIn("CS2_EXECUTOR", launcher)
        self.assertNotIn("FEX", launcher)
        self.assertFalse((ROOT / "server/runtime/Dockerfile.fex").exists())

    def test_all_mode_definitions_and_payloads_are_valid(self) -> None:
        definitions, errors = mode_defs.load_definitions(ROOT / "modes")
        self.assertEqual(errors, [])
        self.assertEqual(set(definitions), {"matchzy", "retakes", "heroshift", "warcraft"})
        for name, definition in definitions.items():
            root = ROOT / "modes" / name
            self.assertTrue((root / "addons").is_dir())
            self.assertTrue((root / "cfg" / definition["startup"]["mode_cfg"]).is_file())
            raw = json.loads((root / "mode.json").read_text(encoding="utf-8"))
            for plugin in raw["plugins"]:
                self.assertNotIn("mounts", plugin)
                self.assertNotIn("build", plugin)
                self.assertTrue((root / plugin["path"]).exists(), f"{name}: {plugin['path']}")
            self.assertFalse((root / "cfg/server.cfg").exists())

    def test_companion_plugins_are_mode_local(self) -> None:
        for name in ("matchzy", "retakes", "heroshift", "warcraft"):
            plugins = ROOT / "modes" / name / "addons/counterstrikesharp/plugins"
            self.assertTrue((plugins / "PanelBridge/PanelBridge.dll").is_file())
            self.assertTrue((plugins / "ClutchAnnouncePlugin/ClutchAnnouncePlugin.dll").is_file())

    def test_mode_manager_accepts_every_repository_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            state = temp / "state"
            server = temp / "server"
            installed = server / "game/csgo/addons/.cs2-manager-versions.json"
            installed.parent.mkdir(parents=True)
            installed.write_text(
                json.dumps(
                    {
                        "metamod": "2.0.0-git1410",
                        "counterstrikesharp": "1.0.371",
                    }
                ),
                encoding="utf-8",
            )
            for name in ("matchzy", "retakes", "heroshift", "warcraft"):
                runtime = state / "runtime" / name / "panel_runtime.cfg"
                runtime.parent.mkdir(parents=True)
                runtime.write_text("echo test\n", encoding="utf-8")
                result = mode_manager.verify_mode(
                    modes_root=ROOT / "modes",
                    mode=name,
                    state_root=state,
                    server_config=ROOT / "server/config/server.cfg",
                    versions_path=ROOT / "server/frameworks/versions.json",
                    installed_versions_path=installed,
                )
                self.assertGreater(result["files"], 1)

    def test_expected_main_plugins_exist(self) -> None:
        expected = {
            "matchzy": "MatchZy/MatchZy.dll",
            "retakes": "RetakesPlugin/RetakesPlugin.dll",
            "heroshift": "HeroShift/HeroShift.dll",
            "warcraft": "WarcraftClassic/WarcraftClassic.dll",
        }
        prefix = Path("addons/counterstrikesharp/plugins")
        for mode, relative in expected.items():
            self.assertTrue((ROOT / "modes" / mode / prefix / relative).is_file())

    def test_no_legacy_runtime_references_remain(self) -> None:
        forbidden = (
            "/manager/",
            "manager/modes",
            "manager/shared",
            "mode-applier",
            "fetch-releases.ps1",
            "./update.ps1",
        )
        extensions = {".py", ".sh", ".ps1", ".yml", ".yaml", ".json", ".md"}
        for path in ROOT.rglob("*"):
            if (
                not path.is_file()
                or path.resolve() == Path(__file__).resolve()
                or path.suffix.lower() not in extensions
                or ".git" in path.parts
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token!r} remains in {path.relative_to(ROOT)}")

    def test_compose_uses_new_build_contexts(self) -> None:
        compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        self.assertIn("context: ./server/runtime", compose)
        self.assertIn("context: ./server/updater", compose)
        self.assertIn("build: ./panel", compose)
        self.assertIn("${PROJECT_PATH}/modes:/modes:ro", compose)
        self.assertNotIn("./manager", compose)


if __name__ == "__main__":
    unittest.main()
