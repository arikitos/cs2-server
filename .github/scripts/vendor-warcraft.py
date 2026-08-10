#!/usr/bin/env python3
"""Vendor a pinned WarcraftClassic source build into the CS2 Manager mode tree."""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def main() -> int:
    if len(sys.argv) != 6:
        raise SystemExit(
            "usage: vendor-warcraft.py <server-root> <source-root> <build-root> <source-ref> <version>"
        )

    server_root = Path(sys.argv[1]).resolve()
    source_root = Path(sys.argv[2]).resolve()
    build_root = Path(sys.argv[3]).resolve()
    source_ref = sys.argv[4].strip().lower()
    version = sys.argv[5].strip()

    if len(source_ref) != 40 or any(c not in "0123456789abcdef" for c in source_ref):
        raise SystemExit("source-ref must be a 40 character lowercase commit SHA")
    if not version or any(c not in "0123456789." for c in version):
        raise SystemExit("version must be a numeric semantic version")

    mode_root = server_root / "manager" / "modes" / "warcraft"
    release_root = mode_root / "release"
    plugin_root = release_root / "plugins" / "WarcraftClassic"
    config_source = source_root / "src" / "WarcraftClassic" / "config.example.json"
    hero_template_path = server_root / "manager" / "modes" / "heroshift" / "mode.json"
    existing_mode_path = mode_root / "mode.json"

    if not build_root.is_dir():
        raise SystemExit(f"build output is missing: {build_root}")

    required_runtime = ["WarcraftClassic.dll", "WarcraftClassic.deps.json"]
    for name in required_runtime:
        if not (build_root / name).is_file():
            raise SystemExit(f"build output does not contain {name}")
    if not (build_root / "lang").is_dir():
        raise SystemExit("build output does not contain lang directory")
    if not config_source.is_file():
        raise SystemExit(f"config template is missing: {config_source}")

    forbidden_runtime = [
        "CounterStrikeSharp.API.dll",
        "Microsoft.Data.Sqlite.dll",
        "SQLitePCLRaw.core.dll",
        "SQLitePCLRaw.provider.e_sqlite3.dll",
        "runtimes",
    ]
    for name in forbidden_runtime:
        if (build_root / name).exists():
            raise SystemExit(f"host or native dependency must not be vendored: {name}")

    shutil.rmtree(release_root, ignore_errors=True)
    plugin_root.mkdir(parents=True, exist_ok=True)
    for name in required_runtime:
        shutil.copy2(build_root / name, plugin_root / name)
    shutil.copytree(build_root / "lang", plugin_root / "lang")

    config_path = mode_root / "config" / "WarcraftClassic.json"
    if not config_path.exists():
        config = load_json(config_source)
        write_json(config_path, config)

    hero_template = load_json(hero_template_path)
    if existing_mode_path.exists():
        mode = load_json(existing_mode_path)
    else:
        mode = copy.deepcopy(hero_template)
        mode["settings"]["defaults"]["hostname"] = "Warcraft 3 Server"

    mode["id"] = "warcraft"
    mode["label"] = "Warcraft Classic"
    mode["implementation"] = "Classic Warcraft 3 races, skills, ultimates and XP progression"
    mode["order"] = 50
    mode["requires"] = {
        "metamod": "2.0.0-git1410",
        "counterstrikesharp": "1.0.371",
    }
    mode["startup"]["mode_cfg"] = "mode_warcraft.cfg"

    warcraft_plugin = {
        "name": "WarcraftClassic",
        "role": "plugin",
        "verify": {
            "required": True,
            "aliases": ["warcraft classic", "warcraftclassic"],
        },
        "mounts": [
            {
                "source": "release/plugins/WarcraftClassic/WarcraftClassic.deps.json",
                "kind": "file",
                "target": "addons/counterstrikesharp/plugins/WarcraftClassic/WarcraftClassic.deps.json",
            },
            {
                "source": "release/plugins/WarcraftClassic/WarcraftClassic.dll",
                "kind": "file",
                "target": "addons/counterstrikesharp/plugins/WarcraftClassic/WarcraftClassic.dll",
            },
            {
                "source": "release/plugins/WarcraftClassic/lang",
                "kind": "dir",
                "target": "addons/counterstrikesharp/plugins/WarcraftClassic/lang",
            },
        ],
    }

    shared_source = mode.get("plugins", [])
    shared_plugins = [
        plugin
        for plugin in shared_source
        if isinstance(plugin, dict) and plugin.get("name") in {"PanelBridge", "ClutchAnnounce"}
    ]
    if not shared_plugins:
        shared_plugins = [
            plugin
            for plugin in hero_template["plugins"]
            if plugin.get("name") in {"PanelBridge", "ClutchAnnounce"}
        ]
    mode["plugins"] = [warcraft_plugin, *shared_plugins]

    configs = [
        cfg
        for cfg in mode.get("configs", [])
        if isinstance(cfg, dict) and cfg.get("name") not in {"WarcraftClassic.json"}
    ]
    if not any(cfg.get("name") == "server.cfg" for cfg in configs):
        configs.insert(
            0,
            next(cfg for cfg in hero_template["configs"] if cfg.get("name") == "server.cfg"),
        )
    configs.append(
        {
            "name": "WarcraftClassic.json",
            "source": "config/WarcraftClassic.json",
            "kind": "file",
            "target": "addons/counterstrikesharp/configs/plugins/WarcraftClassic/WarcraftClassic.json",
        }
    )
    mode["configs"] = configs
    write_json(existing_mode_path, mode)

    runtime_path = mode_root / "cfg" / "panel_runtime.cfg"
    if not runtime_path.exists():
        runtime_template = server_root / "manager" / "modes" / "heroshift" / "cfg" / "panel_runtime.cfg"
        runtime_lines: list[str] = []
        hostname = mode["settings"]["defaults"]["hostname"]
        for line in runtime_template.read_text(encoding="utf-8").splitlines():
            if line.startswith('echo "[CS2 Manager] Applying '):
                runtime_lines.append('echo "[CS2 Manager] Applying warcraft runtime settings"')
            elif line.startswith("hostname "):
                runtime_lines.append(f'hostname "{hostname}"')
            else:
                runtime_lines.append(line)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text("\n".join(runtime_lines) + "\n", encoding="utf-8")

    marker = {
        "schemaVersion": 2,
        "packageType": "mode",
        "id": "warcraft",
        "component": "warcraft-classic",
        "name": "WarcraftClassic",
        "version": version,
        "managed": False,
        "installStrategy": "replace-roots",
        "installRoots": ["plugins/WarcraftClassic"],
        "sourceArchive": f"arikitos/cs2-warcraft3@{source_ref}",
        "note": "Pinned source build vendored by GitHub Actions. Host assemblies and native database libraries are intentionally excluded. Runtime files are mounted granularly so plugin-generated data is not manager-owned.",
    }
    write_json(mode_root / "packages" / "warcraft-classic.json", marker)

    readme = server_root / "README.md"
    text = readme.read_text(encoding="utf-8")
    hero_row = "| HeroShift | HeroShift, RayTrace, RayTraceImpl, RayTraceApi, PanelBridge | ClutchAnnounce |"
    warcraft_row = "| Warcraft Classic | WarcraftClassic, PanelBridge | ClutchAnnounce |"
    if warcraft_row not in text and hero_row in text:
        text = text.replace(hero_row, hero_row + "\n" + warcraft_row)
    inbox_line = "installs/modes/heroshift/heroshift/"
    warcraft_inbox = "installs/modes/warcraft/warcraft-classic/"
    if warcraft_inbox not in text and inbox_line in text:
        text = text.replace(inbox_line, inbox_line + "\n" + warcraft_inbox)
    readme.write_text(text, encoding="utf-8")

    print(f"Vendored WarcraftClassic {version} from {source_ref}")
    print("Runtime mount entries: 3")
    print("Host runtime safety: CounterStrikeSharp and native SQLite dependencies are excluded")
    print("Operator config safety: existing Warcraft config and runtime cfg are preserved")
    print("Persistent XP safety: plugin data/ is intentionally absent from managed targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
