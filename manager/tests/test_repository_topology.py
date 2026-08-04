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

    def test_compose_bounds_game_and_panel_logs(self) -> None:
        text = (ROOT / "compose.yml").read_text(encoding="utf-8")
        self.assertIn('max-size: "10m"', text)
        self.assertIn('max-file: "3"', text)
        self.assertIn('max-size: "5m"', text)
        self.assertIn('max-file: "2"', text)

    def test_updater_image_is_explicit_and_never_pulled_by_compose(self) -> None:
        text = (ROOT / "compose.yml").read_text(encoding="utf-8")
        updater = text.split("  cs2-updater:\n", 1)[1].split(
            "\n  cs2-modinstaller:",
            1,
        )[0]
        self.assertIn("image: cs2-manager-updater:pinned", updater)
        self.assertIn("pull_policy: never", updater)
        panel = text.split("  panel:\n", 1)[1]
        self.assertIn("UPDATER_IMAGE: cs2-manager-updater:pinned", panel)
        self.assertIn("UPDATER_BUILD_CONTEXT: /project/updater", panel)
        self.assertIn("CS2_BASE_IMAGE:", panel)

    def test_setup_builds_and_verifies_updater_before_panel_start(self) -> None:
        script = (ROOT / "setup.ps1").read_text(encoding="utf-8")
        build = script.index("build cs2-updater")
        inspect = script.index("image inspect cs2-manager-updater:pinned")
        panel = script.index("up -d --build --no-deps panel")
        self.assertLess(build, inspect)
        self.assertLess(inspect, panel)

    def test_heroshift_release_overlay_is_versioned_and_mounted(self) -> None:
        compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        self.assertEqual(compose.count("HEROSHIFT_RELEASE_PATH"), 2)
        self.assertIn("target: /manager/modes/heroshift/release", compose)
        self.assertIn("target: /modes/heroshift/release", compose)

        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("HEROSHIFT_RELEASE_PATH=./manager/modes/heroshift", env)

        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("manager/releases/heroshift/", ignored)

        manifest = json.loads(
            (MANAGER / "modes/heroshift/mode.json").read_text(encoding="utf-8")
        )
        release_sources = [
            mount["source"]
            for plugin in manifest["plugins"]
            if plugin["name"] in {"HeroShift", "RayTrace"}
            for mount in plugin["mounts"]
        ]
        self.assertTrue(release_sources)
        self.assertTrue(all(source.startswith("release/") for source in release_sources))

    def test_heroshift_installer_pins_and_verifies_the_uploaded_release(self) -> None:
        script = (MANAGER / "scripts/install-heroshift-release.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('ExpectedVersion = "v1.0.1"', script)
        self.assertIn(
            "5e4e2901757a234c43b0c844a99e118985a1f2474244c0d3dcedabc6f4770b0e",
            script,
        )
        self.assertIn("Manifest SHA256 mismatch", script)
        self.assertIn("Unsafe ZIP path", script)
        self.assertIn("HEROSHIFT_RELEASE_PATH", script)

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

    def test_updater_image_normalizes_windows_line_endings(self) -> None:
        dockerfile = (MANAGER / "updater/Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "sed -i 's/\\r$//' /usr/local/bin/updater.sh",
            dockerfile,
        )

    def test_updater_verifies_metamod_inside_searchpaths(self) -> None:
        updater = (MANAGER / "updater/updater.sh").read_text(encoding="utf-8")
        self.assertIn("metamod_search_path_present", updater)
        self.assertIn("insert_metamod_search_path", updater)
        self.assertNotIn(
            'grep -q "csgo/addons/metamod" "${GAMEINFO}"',
            updater,
        )

    def test_panel_uses_guarded_wsgi_entrypoint(self) -> None:
        dockerfile = (MANAGER / "panel/Dockerfile").read_text(encoding="utf-8")
        wsgi = (MANAGER / "panel/wsgi.py").read_text(encoding="utf-8")
        self.assertIn("COPY maintenance_guard.py .", dockerfile)
        self.assertIn("COPY wsgi.py .", dockerfile)
        self.assertIn('"wsgi:app"', dockerfile)
        self.assertIn("install(panel)", wsgi)

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
