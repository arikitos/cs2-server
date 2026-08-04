from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

version = sys.argv[1] if len(sys.argv) > 1 else "v9.9.9"
root = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path.cwd()
package = root / f"HeroShift-{version}.zip"

files = {
    "addons/counterstrikesharp/plugins/HeroShift/HeroShift.dll": b"hero",
    "addons/counterstrikesharp/gamedata/HeroShift.gamedata.json": b"{}\n",
    "addons/metamod/RayTrace.vdf": b"raytrace\n",
    "addons/RayTrace/gamedata.json": b"{}\n",
    "addons/RayTrace/bin/linuxsteamrt64/raytrace.so": b"native",
    "addons/counterstrikesharp/plugins/RayTraceImpl/RayTraceImpl.dll": b"impl",
    "addons/counterstrikesharp/shared/RayTraceApi/RayTraceApi.dll": b"api",
    "THIRD_PARTY_NOTICES.md": b"test notice\n",
    "licenses/RayTrace-GPL-3.0.txt": b"test license\n",
}
manifest = {
    "package": "HeroShift",
    "version": version,
    "files": [
        {
            "path": path,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for path, data in files.items()
    ],
}

with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
    for path, data in files.items():
        archive.writestr(path, data)
    archive.writestr("package-manifest.json", json.dumps(manifest, indent=2) + "\n")

print(package)
