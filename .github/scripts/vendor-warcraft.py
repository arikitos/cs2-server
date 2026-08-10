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


def main() -> int:
    if len(sys.argv) != 6:
        raise SystemExit(
            "usage: vendor-warcraft.py <server-root> <source-root> <publish-root> <source-ref> <version>"
        )

    server_root = Path(sys.argv[1]).resolve()
    source_root = Path(sys.argv[2]).resolve()
    publish_root = Path(sys.argv[3]).resolve()
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
    template_path = server_root / "manager" / "modes" / "heroshift" / "mode.json"

    if not publish_root.is_dir():
        raise SystemExit(f"publish output is missing: {publish_root}")
    if not (publish_root / "WarcraftClassic.dll").is_file():
        raise SystemExit("publish output does not contain WarcraftClassic.dll")
    if not config_source.is_file():
        raise SystemExit(f"config template is missing: {config_source}")

    shutil.rmtree(release_root, ignore_errors=True)
    plugin_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publish_root, plugin_root)

    for pdb in plugin_root.rglob("*.pdb"):
        pdb.unlink()

    config = json.loads(config_source.read_text(encoding="utf-8"))
    write_json(mode_root / "config" / "WarcraftClassic.json", config)

    template = json.loads(template_path.read_text(encoding="utf-8"))
    mode = copy.deepcopy(template)
    mode["id"] = "warcraft"
    mode["label"] = "Warcraft Classic"
    mode["implementation"] = "Classic Warcraft 3 races, skills, ultimates and XP progression"
    mode["order"] = 50
    mode["startup"]["mode_cfg"] = "mode_warcraft.cfg"
    mode["settings"]["defaults"]["hostname"] = "Warcraft Classic Server"

    excluded_runtime_names = {
        "config.example.json",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
    }
    mounts: list[dict[str, object]] = []
    for child in sorted(plugin_root.iterdir(), key=lambda item: item.name.lower()):
        if child.name in excluded_runtime_names or child.suffix.lower() == ".pdb":
            continue
        mounts.append(
            {
                "source": f"release/plugins/WarcraftClassic/{child.name}",
                "kind": "dir" if child.is_dir() else "file",
                "target": f"addons/counterstrikesharp/plugins/WarcraftClassic/{child.name}",
            }
        )

    if not any(item["target"].endswith("/WarcraftClassic.dll") for item in mounts):
        raise SystemExit("WarcraftClassic.dll was not selected for deployment")

    warcraft_plugin = {
        "name": "WarcraftClassic",
        "role": "plugin",
        "verify": {
            "required": True,
            "aliases": ["warcraft classic", "warcraftclassic"],
        },
        "mounts": mounts,
    }
    shared_plugins = [
        plugin
        for plugin in template["plugins"]
        if plugin.get("name") in {"PanelBridge", "ClutchAnnounce"}
    ]
    mode["plugins"] = [warcraft_plugin, *shared_plugins]

    shared_server_cfg = next(
        cfg for cfg in template["configs"] if cfg.get("name") == "server.cfg"
    )
    mode["configs"] = [
        shared_server_cfg,
        {
            "name": "WarcraftClassic.json",
            "source": "config/WarcraftClassic.json",
            "kind": "file",
            "target": "addons/counterstrikesharp/configs/plugins/WarcraftClassic/WarcraftClassic.json",
        },
    ]
    allowed_actions = {"restart_round", "warmup_end", "kick_bots"}
    mode["actions"] = [
        action for action in template.get("actions", []) if action.get("key") in allowed_actions
    ]
    write_json(mode_root / "mode.json", mode)

    runtime_template = server_root / "manager" / "modes" / "heroshift" / "cfg" / "panel_runtime.cfg"
    runtime_lines: list[str] = []
    for line in runtime_template.read_text(encoding="utf-8").splitlines():
        if line.startswith('echo "[CS2 Manager] Applying '):
            runtime_lines.append('echo "[CS2 Manager] Applying warcraft runtime settings"')
        elif line.startswith("hostname "):
            runtime_lines.append('hostname "Warcraft Classic Server"')
        else:
            runtime_lines.append(line)
    (mode_root / "cfg" / "panel_runtime.cfg").write_text(
        "\n".join(runtime_lines) + "\n", encoding="utf-8"
    )

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
        "note": "Pinned source build vendored by GitHub Actions. Runtime files are mounted granularly so plugin-generated data is not manager-owned.",
    }
    write_json(mode_root / "packages" / "warcraft-classic.json", marker)

    server_path = server_root / "manager" / "data" / "server.json"
    server = json.loads(server_path.read_text(encoding="utf-8"))
    server["last_mode"] = "warcraft"
    write_json(server_path, server)

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
    print(f"Runtime mount entries: {len(mounts)}")
    print("Persistent XP safety: plugin data/ is intentionally absent from managed targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
