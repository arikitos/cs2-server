# CS2 Manager

A Docker Compose stack for one persistent Counter-Strike 2 dedicated server and
one active game mode. The panel controls lifecycle, mode selection, match
settings, RCON, logs and maintenance without exposing a host shell to the
browser.

## Architecture

The persistent CS2 installation is composed from three layers.

1. Base runtime, CS2, Metamod and CounterStrikeSharp.
2. Shared manager content, such as `server.cfg` and `PanelBridge`.
3. The selected mode release and its editable configuration.

`manager/runtime/mode_applier.py` validates and stages the complete next layer,
removes only files recorded in the previous manager inventory, installs the new
layer, and atomically records the result. Unmanaged plugins are preserved.

The active inventory is stored at.

```text
<CS2_DATA_PATH>/.cs2-manager/managed-files.json
```

## Repository layout

```text
cs2-server/
├── compose.yml
├── setup.ps1
├── update.ps1
├── installs/
│   ├── modes/
│   │   ├── faceit/
│   │   ├── retake/
│   │   └── heroshift/
│   └── shared/
│       └── panelbridge/
└── manager/
    ├── modes/
    │   └── <mode>/
    │       ├── mode.json
    │       ├── installed.json
    │       ├── release/
    │       ├── config/
    │       ├── cfg/
    │       └── src/
    ├── shared/
    │   ├── cfg/
    │   ├── components/
    │   │   └── panelbridge/
    │   │       ├── installed.json
    │   │       ├── release/
    │   │       └── src/
    │   └── frameworks/
    │       ├── versions.json
    │       └── install-linux.sh
    ├── runtime/
    ├── updater/
    ├── panel/
    ├── data/
    ├── backups/
    └── scripts/
```

### Mode contract

Every mode follows the same structure.

`mode.json` declares compatibility, deployment targets, settings and panel
actions.

`release` contains replaceable runtime files supplied by a versioned package.
Manual replacement is possible here, although `installed.json` should then be
updated deliberately or the next managed package should be installed with
`-Force`.

`config` contains operator-managed configuration. Package updates never replace
this directory.

`cfg` contains CS2 configuration owned by the mode.

`src` contains local source projects used to build mode-specific helpers. It is
not deployed directly.

`installed.json` records the managed package version and archive hash. Existing
bundled FaceIt and Retake assets use a `0.0.0` repository baseline because their
original upstream package versions were not encoded in the previous layout.
The first versioned package supersedes that baseline.

### Shared contract

Shared content lives only under `manager/shared`.

`manager/shared/cfg` contains configuration deployed for every mode.

`manager/shared/components/<id>` uses the same `release`, `src` and
`installed.json` separation as a mode package. `PanelBridge` is stored here and
referenced by every mode manifest.

`manager/shared/frameworks` owns the pinned Metamod and CounterStrikeSharp
version contract and the framework installer. Framework binaries remain in the
persistent CS2 installation because they are runtime foundations, not mode
payloads.

## Modes

| Mode | Main plugin | Mode-specific dependencies |
|---|---|---|
| FaceIt | MatchZy | AutoReady |
| Retake | RetakesPlugin | InstadefusePlugin, RetakesPluginShared |
| HeroShift | HeroShift | RayTrace, RayTraceImpl, RayTraceApi |

All modes use the same `cs2-game` container. Mode switching restarts the game
process, applies the selected manifest and removes only the previous
manager-owned mode files.

## Package updates

Drop package archives under the relevant inbox.

```text
installs/modes/heroshift/HeroShift-v1.0.6.zip
installs/modes/faceit/FaceIt-v1.1.0.zip
installs/modes/retake/Retake-v2.0.0.zip
installs/shared/panelbridge/PanelBridge-v1.1.0.zip
```

Then run.

```powershell
./update.ps1
```

Useful scopes.

```powershell
./update.ps1 -Mode heroshift
./update.ps1 -SharedOnly
./update.ps1 -WhatIf
./update.ps1 -Force
./update.ps1 -NoRestart
./update.ps1 -KeepBackups 5
```

The updater performs the following transaction for each package identity.

1. Scans every ZIP under `installs`.
2. Reads `package-manifest.json` without trusting the filename.
3. Rejects unsafe paths, duplicate entries and unsupported package identities.
4. Verifies every declared file size and SHA256.
5. Selects the highest semantic version for each component.
6. Compares it with `installed.json`.
7. Skips equal or older versions and leaves all ZIP files untouched.
8. Extracts a newer package into a temporary staging directory.
9. Moves the current `release` into `manager/backups/packages`.
10. Activates the staged release and writes a new `installed.json`.
11. Restores the previous release automatically if activation fails.
12. Removes lower-version ZIP files only after the newer version is active.
13. Keeps the newly installed ZIP in `installs`.
14. Recreates `cs2-game` only when a changed shared component or the active mode
    requires it. A stopped game container remains stopped.

Updates are serialized by `manager/data/package-update.lock`.

### Standard package format

A standard package contains `package-manifest.json` and a `payload` directory
whose contents mirror the destination `release` directory.

```text
package-manifest.json
payload/
├── plugins/
├── utils/
└── gamedata/
```

Example manifest.

```json
{
  "schemaVersion": 1,
  "packageType": "mode",
  "id": "heroshift",
  "name": "HeroShift",
  "version": "1.0.6",
  "payloadRoot": "payload",
  "files": [
    {
      "path": "payload/plugins/HeroShift/HeroShift.dll",
      "size": 123456,
      "sha256": "lowercase-sha256"
    }
  ]
}
```

Supported `packageType` values are `mode` and `shared`. IDs use lowercase
letters, numbers and hyphens.

Current HeroShift release archives are also supported through a compatibility
adapter. Their existing `package: HeroShift`, `version: vX.Y.Z` manifest and
`addons/...` layout are verified and converted into
`manager/modes/heroshift/release` during staging.

See `installs/README.md` for the full package contract.

## Manual replacement

Runtime files may be replaced directly under.

```text
manager/modes/<mode>/release
manager/shared/components/<component>/release
```

Editable configurations remain under each mode's `config` directory and should
not be copied into `release`.

After a manual replacement, restart the active mode. The manual change does not
alter `installed.json`, so a later `update.ps1` run still compares against the
last managed version. Use `-Force` to deliberately reinstall the selected
package.

## Framework compatibility

Every `mode.json` declares required Metamod and CounterStrikeSharp versions.
The manager-wide source of truth is.

```text
manager/shared/frameworks/versions.json
```

Normal startup refuses to deploy a mode when its requirements, the manager
version contract and the installed marker disagree.

Install the pinned framework pair with.

```bash
docker compose --profile maintenance run --rm cs2-modinstaller
```

The installer writes.

```text
<CS2_DATA_PATH>/game/csgo/addons/.cs2-manager-versions.json
```

Framework upgrades are deliberate compatibility operations. Update
`manager/shared/frameworks/versions.json`, update every mode requirement,
rebuild affected local plugins and run the live smoke test.

## Setup

1. Copy `.env.example` to `.env` and configure the token, RCON password, panel
   credentials, `CS2_DATA_PATH` and `MANAGER_PATH`.
2. Place any initial mode packages under `installs`.
3. Run the setup script.

```powershell
./setup.ps1
```

`setup.ps1` applies pending packages with `update.ps1 -NoRestart`, validates the
Compose model, builds the maintenance image, creates the stopped game container
and starts the panel.

On Linux.

```bash
manager/scripts/start.sh
```

The Linux start script reports pending ZIP files but does not mutate packages.
Run `pwsh ./update.ps1` first when PowerShell is available, or prepare the mode
release directories before starting.

## CS2 maintenance

The normal game container never runs SteamCMD. Base game update and validation
run only through `cs2-updater` and require the exact confirmation phrase.

```bash
CS2_UPDATER_CONFIRM="UPDATE CS2" \
  docker compose --profile maintenance run --rm cs2-updater
```

Supported updater modes are `update`, `validate` and `repair-metamod`.

## Deployment flow

1. The panel writes `manager/data/runtime/active-mode.json`.
2. `cs2-game` starts or restarts.
3. The runtime launcher verifies framework compatibility.
4. `mode_applier.py` validates all mode and shared sources.
5. The complete next layer is staged.
6. Previous inventory-owned targets are removed.
7. The staged layer is installed and inventory is replaced atomically.
8. CS2 starts with the selected format, map and cfg files.
9. The panel waits for RCON and verifies required plugins.

Native modules such as RayTrace are never hot-unloaded.

## Backups and rollback

Package updates store release backups under.

```text
manager/backups/packages/<package-type>/<id>/<new-version>/
```

Panel-managed configuration backups are stored separately under.

```text
manager/backups/config/<mode-id>/
```

`update.ps1` keeps three backups per component by default. Configure the count
with `-KeepBackups`.

The older topology migration and rollback scripts remain under
`manager/scripts`. They back up and restore the complete manager directories,
including the new shared framework path.

## Verification

Repository checks.

```bash
python -m unittest discover -s manager/tests -v
python -m py_compile \
  manager/panel/app.py \
  manager/panel/mode_defs.py \
  manager/runtime/mode_applier.py
bash -n manager/runtime/runtime-launcher.sh
bash -n manager/scripts/start.sh
bash -n manager/scripts/stop.sh
bash -n manager/shared/frameworks/install-linux.sh
bash -n manager/scripts/smoke-test.sh
```

After deployment on a real server.

```bash
manager/scripts/smoke-test.sh
```

## Security properties

The panel binds to localhost by default. Use a VPN or secured reverse proxy for
remote access.

Package paths and manifest paths are validated before extraction. Every payload
file is verified by SHA256. Extraction never writes outside the selected staging
directory.

Only inventory-owned mode targets are removed from the persistent server.
Framework roots are reserved from mode manifests. The browser has no arbitrary
shell or Docker command surface.
