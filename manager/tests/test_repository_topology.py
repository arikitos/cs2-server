from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANAGER = ROOT / "manager"


class RepositoryTopologyTests(unittest.TestCase):
    def test_compose_has_one_game_service(self) -> None:
        text = (ROOT / "compose.yml").read_text(encoding="utf-8")
        services_block = text.split("services:\n", 1)[1]
        services = re.findall(r"^  ([a-z0-9][a-z0-9-]*):$", services_block, re.MULTILINE)
        self.assertEqual(services, ["cs2-game", "cs2-updater", "cs2-modinstaller", "panel"])
        for old in ("cs2-faceit", "cs2-retakes", "cs2-heroshift"):
            self.assertNotIn(f"  {old}:", text)

    def test_framework_installer_never_follows_latest(self) -> None:
        script = (MANAGER / "scripts/install-mods-linux.sh").read_text(encoding="utf-8")
        self.assertNotIn("releases/latest", script)
        self.assertNotIn("mmsource-latest", script)
        versions = json.loads((MANAGER / "versions.json").read_text(encoding="utf-8"))
        css_version = versions["counterstrikesharp"]["version"]
        self.assertIn(f"tags/v{css_version}", versions["counterstrikesharp"]["release_api"])

    def test_raytrace_is_declared_only_by_heroshift(self) -> None:
        declarations = {}
        for manifest_path in (MANAGER / "modes").glob("*/mode.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            targets = []
            for plugin in manifest["plugins"]:
                targets.extend(row["target"] for row in plugin["mounts"])
            declarations[manifest["id"]] = [target for target in targets if "RayTrace" in target]
        self.assertEqual(declarations["faceit"], [])
        self.assertEqual(declarations["retake"], [])
        self.assertGreaterEqual(len(declarations["heroshift"]), 5)

    def test_launcher_applies_mode_before_starting_cs2(self) -> None:
        launcher = (MANAGER / "runtime/runtime-launcher.sh").read_text(encoding="utf-8")
        self.assertLess(launcher.index("/usr/local/bin/mode-applier"), launcher.index("exec ./cs2.sh"))
        self.assertNotIn("app_update", launcher)
        self.assertNotIn("steamcmd.sh", launcher.lower())

    def test_runtime_applier_avoids_python_310_only_zip_strict(self) -> None:
        applier = (MANAGER / "runtime/mode_applier.py").read_text(encoding="utf-8")
        self.assertNotIn("strict=True", applier)

    def test_runtime_applier_avoids_python_310_path_write_text_newline(
        self,
    ) -> None:
        applier = (MANAGER / "runtime/mode_applier.py").read_text(
            encoding="utf-8"
        )
        unsupported = re.compile(
            r"\.write_text\([^)]*\bnewline\s*=",
            re.DOTALL,
        )
        self.assertNotRegex(applier, unsupported)

    def test_runtime_image_normalizes_windows_line_endings(self) -> None:
        dockerfile = (MANAGER / "runtime/Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "sed -i 's/\\r$//' "
            "/usr/local/bin/runtime-launcher.sh "
            "/usr/local/bin/mode-applier",
            dockerfile,
        )

    def test_runtime_launcher_avoids_python_310_path_write_text_newline(
        self,
    ) -> None:
        launcher = (MANAGER / "runtime/runtime-launcher.sh").read_text(
            encoding="utf-8"
        )
        unsupported = re.compile(
            r"\.write_text\([^)]*\bnewline\s*=",
            re.DOTALL,
        )
        self.assertNotRegex(launcher, unsupported)


if __name__ == "__main__":
    unittest.main()
