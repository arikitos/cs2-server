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

    def test_compose_mounts_modes_and_shared_once_without_mode_exceptions(self) -> None:
        text = (ROOT / "compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("HEROSHIFT_RELEASE_PATH", text)
        self.assertNotIn("manager/releases/heroshift", text)
        self.assertEqual(text.count("source: ./manager/modes"), 1)
        self.assertEqual(text.count("source: ./manager/shared"), 1)
        self.assertIn("MODE_VERSIONS_PATH: /manager/shared/frameworks/versions.json", text)
        self.assertIn(
            'entrypoint: ["bash", "/project/manager/shared/frameworks/install-linux.sh"]',
            text,
        )

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

    def test_setup_applies_pending_packages_before_container_creation(self) -> None:
        script = (ROOT / "setup.ps1").read_text(encoding="utf-8")
        update = script.index('"update.ps1") -NoRestart')
        create = script.index("docker compose create --build cs2-game")
        panel = script.index("up -d --build --no-deps panel")
        self.assertLess(update, create)
        self.assertLess(create, panel)

    def test_every_mode_uses_the_same_directory_contract(self) -> None:
        for mode in ("faceit", "retake", "heroshift"):
            root = MANAGER / "modes" / mode
            self.assertTrue((root / "mode.json").is_file())
            self.assertTrue((root / "release").is_dir())
            self.assertTrue((root / "cfg").is_dir())
            self.assertTrue((root / "README.md").is_file())
            self.assertTrue((root / "installed.json").is_file())

            manifest = json.loads((root / "mode.json").read_text(encoding="utf-8"))
            owned_sources = [
                mount["source"]
                for plugin in manifest["plugins"]
                for mount in plugin["mounts"]
                if not mount.get("shared")
            ]
            runtime_sources = [
                source for source in owned_sources
                if source.startswith(("plugins/", "utils/", "gamedata/", "release/"))
            ]
            self.assertTrue(runtime_sources)
            self.assertTrue(all(source.startswith("release/") for source in runtime_sources))

    def test_shared_panelbridge_has_release_and_source_separation(self) -> None:
        root = MANAGER / "shared/components/panelbridge"
        self.assertTrue((root / "release/plugins/PanelBridge/PanelBridge.dll").is_file())
        self.assertTrue((root / "src/PanelBridge/PanelBridge.csproj").is_file())
        self.assertTrue((root / "installed.json").is_file())

        for manifest_path in (MANAGER / "modes").glob("*/mode.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            panelbridge = next(row for row in manifest["plugins"] if row["name"] == "PanelBridge")
            source = panelbridge["mounts"][0]["source"]
            self.assertEqual(source, "components/panelbridge/release/plugins/PanelBridge")
            self.assertTrue(panelbridge["mounts"][0]["shared"])

    def test_framework_contract_is_under_shared(self) -> None:
        installer = MANAGER / "shared/frameworks/install-linux.sh"
        versions_path = MANAGER / "shared/frameworks/versions.json"
        self.assertTrue(installer.is_file())
        self.assertTrue(versions_path.is_file())
        self.assertFalse((MANAGER / "versions.json").exists())
        script = installer.read_text(encoding="utf-8")
        self.assertNotIn("releases/latest", script)
        self.assertNotIn("mmsource-latest", script)
        versions = json.loads(versions_path.read_text(encoding="utf-8"))
        css_version = versions["counterstrikesharp"]["version"]
        self.assertIn(f"tags/v{css_version}", versions["counterstrikesharp"]["release_api"])

    def test_package_updater_enforces_transactional_versioned_updates(self) -> None:
        script = (ROOT / "update.ps1").read_text(encoding="utf-8")
        for required in (
            "package-manifest.json",
            "Manifest SHA256 mismatch",
            "Unsafe ZIP path",
            "installed.json",
            "package-update.lock",
            "Move-Item -LiteralPath $paths.ReleaseRoot -Destination (Join-Path $backupPath 'release')",
            "Copy-Item -LiteralPath $paths.MarkerPath -Destination (Join-Path $backupPath 'installed.json')",
            "Removed superseded archive",
            "legacy-heroshift",
            "SupportsShouldProcess",
        ):
            self.assertIn(required, script)
        self.assertIn("$comparison -le 0", script)
        self.assertIn("$_.Version -lt $selected.Version", script)

    def test_package_inboxes_are_present_and_archives_are_ignored(self) -> None:
        for path in (
            ROOT / "installs/modes/faceit",
            ROOT / "installs/modes/retake",
            ROOT / "installs/modes/heroshift",
            ROOT / "installs/shared/panelbridge",
        ):
            self.assertTrue(path.is_dir())
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("installs/**/*.zip", ignored)
        self.assertNotIn("manager/releases/heroshift", ignored)

    def test_legacy_heroshift_paths_are_removed(self) -> None:
        for path in (
            ROOT / "install-heroshift.ps1",
            ROOT / "install-heroshift.sh",
            ROOT / "HEROSHIFT_INSTALL.md",
            MANAGER / "scripts/install-heroshift-release.ps1",
            MANAGER / "scripts/install-heroshift-release.sh",
        ):
            self.assertFalse(path.exists())
        searchable = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [ROOT / "compose.yml", ROOT / ".env.example", ROOT / "setup.ps1"]
        )
        self.assertNotIn("HEROSHIFT_RELEASE_PATH", searchable)
        self.assertNotIn("manager/releases/heroshift", searchable)

    def test_release_debug_symbols_and_config_backups_are_cleaned(self) -> None:
        self.assertEqual(list((MANAGER / "modes").glob("*/release/**/*.pdb")), [])
        self.assertEqual(list((MANAGER / "modes").glob("*/config/*.bak-*")), [])


    def test_panel_writes_config_backups_outside_mode_directories(self) -> None:
        panel = (MANAGER / "panel/app.py").read_text(encoding="utf-8")
        self.assertIn('BACKUPS_DIR / "config" / mode_id', panel)
        self.assertIn("HEROSHIFT_BUILT_IN_SKILL_COUNT = 146", panel)

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
        self.assertIn("/manager/shared/frameworks/versions.json", launcher)
        self.assertNotIn("app_update", launcher)
        self.assertNotIn("steamcmd.sh", launcher.lower())

    def test_runtime_applier_avoids_unsupported_python_features(self) -> None:
        applier = (MANAGER / "runtime/mode_applier.py").read_text(encoding="utf-8")
        self.assertNotIn("strict=True", applier)
        unsupported = re.compile(r"\.write_text\([^)]*\bnewline\s*=", re.DOTALL)
        self.assertNotRegex(applier, unsupported)

    def test_runtime_and_updater_images_normalize_line_endings(self) -> None:
        runtime = (MANAGER / "runtime/Dockerfile").read_text(encoding="utf-8")
        updater = (MANAGER / "updater/Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "sed -i 's/\\r$//' "
            "/usr/local/bin/runtime-launcher.sh "
            "/usr/local/bin/mode-applier",
            runtime,
        )
        self.assertIn("sed -i 's/\\r$//' /usr/local/bin/updater.sh", updater)

    def test_updater_verifies_metamod_inside_searchpaths(self) -> None:
        updater = (MANAGER / "updater/updater.sh").read_text(encoding="utf-8")
        self.assertIn("metamod_search_path_present", updater)
        self.assertIn("insert_metamod_search_path", updater)
        self.assertNotIn('grep -q "csgo/addons/metamod" "${GAMEINFO}"', updater)

    def test_panel_uses_guarded_wsgi_entrypoint(self) -> None:
        dockerfile = (MANAGER / "panel/Dockerfile").read_text(encoding="utf-8")
        wsgi = (MANAGER / "panel/wsgi.py").read_text(encoding="utf-8")
        self.assertIn("COPY maintenance_guard.py .", dockerfile)
        self.assertIn("COPY wsgi.py .", dockerfile)
        self.assertIn('"wsgi:app"', dockerfile)
        self.assertIn("install_maintenance_guard(panel)", wsgi)
        self.assertIn("install_config_guard(panel)", wsgi)


if __name__ == "__main__":
    unittest.main()
