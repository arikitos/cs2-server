# CS2 Manager

A Docker Compose stack for one persistent Counter-Strike 2 dedicated server and one active game mode. The panel controls lifecycle, mode selection, match settings, RCON, logs and maintenance without exposing a host shell to the browser.

## Architecture

The persistent server is composed from three layers.

1. CS2, Metamod and CounterStrikeSharp.
2. Shared manager content, such as `server.cfg`, `PanelBridge` and optional shared plugins.
3. The selected mode, including its runtime packages, configuration and cfg files.

`manager/runtime/mode_applier.py` validates and stages the complete next layer, removes only paths recorded in the previous manager inventory, installs the new layer and atomically records the result. Unmanaged server plugins are preserved.

The active inventory is stored at.

```text
<CS2_DATA_PATH>/.cs2-manager/managed-files.json
```

## Repository layout

```text
cs2-server/
├── compose.yml
├── setup.ps1
├── fetch-releases.ps1
├── update.ps1
├── installs/
│   ├── sources.json
│   ├── modes/
│   │   ├── faceit/matchzy/
│   │   ├── retake/retakes/
│   │   ├── retake/instadefuse/
│   │   ├── retake/instaplant/
│   │   └── heroshift/heroshift/
│   └── shared/
│       └── clutch-announce/
└── manager/
    ├── modes/
    │   └── <mode>/
    │       ├── mode.json
    │       ├── packages/
    │       ├── release/
    │       ├── config/
    │       ├── cfg/
    │       └── src/
    ├── shared/
    │   ├── cfg/
    │   ├── components/
    │   │   ├── panelbridge/
    │   │   └── clutch-announce/
    │   └── frameworks/
    │       ├── versions.json
    │       └── install-linux.sh
    ├── runtime/
    ├── updater/
    ├── panel/
    ├── data/
    ├── backups/
    └── scripts/
```

## Directory contracts

Every mode owns everything specific to it under `manager/modes/<mode>`.

`mode.json` declares framework compatibility, deployment targets, settings, optional components and panel actions.

`release` contains replaceable runtime files. Each independently versioned plugin owns one or more roots below this directory.

`packages` contains one installed marker per independently versioned component. Updating Instadefuse therefore does not replace Retakes, and updating MatchZy does not replace AutoReady.

`config` contains operator-managed configuration. Package updates never replace this directory.

`cfg` contains CS2 configuration owned by the mode.

`src` contains local source projects. It is not deployed directly.

Shared content lives under `manager/shared`.

`manager/shared/components` contains shared plugins. `PanelBridge` is bundled locally. `ClutchAnnounce` is an optional shared component and is deployed into every mode after it is installed.

`manager/shared/frameworks` contains the pinned Metamod and CounterStrikeSharp contract. Framework binaries remain inside the persistent CS2 installation because they are runtime foundations rather than mode packages.

## Modes and components

| Mode | Required runtime | Optional runtime |
|---|---|---|
| FaceIt | MatchZy, AutoReady, PanelBridge | ClutchAnnounce |
| Retake | RetakesPlugin, RetakesPluginShared, Instadefuse, PanelBridge | ClutchAnnounce, Instaplant |
| HeroShift | HeroShift, RayTrace, RayTraceImpl, RayTraceApi, PanelBridge | ClutchAnnounce |
| Warcraft Classic | WarcraftClassic, PanelBridge | ClutchAnnounce |

The bundled baseline currently contains MatchZy `0.8.15`, Retakes `3.1.0`, Instadefuse `2.0.0`, AutoReady `1.0.0` and PanelBridge `1.0.0`.

Instaplant is disabled in `installs/sources.json` by default. Retakes already has `BombSettings.IsAutoPlantEnabled` enabled. Before installing Instaplant, disable the Retakes built-in autoplant to avoid two plugins controlling the same action.

## Updating from official releases

The normal online workflow is.

```powershell
./update.ps1 -FetchLatest -WhatIf
./update.ps1 -FetchLatest
```

`fetch-releases.ps1` reads `installs/sources.json`, queries each configured GitHub repository, selects the approved release asset, verifies the GitHub asset digest when one is provided, rejects unsafe ZIP paths, removes debug symbols, normalizes the upstream layout and writes a verified local package under `installs`.

`update.ps1` then compares each package with its component marker and installs only a newer version.

Default online sources are.

```text
shobhit-pathak/MatchZy
B3none/cs2-retakes
B3none/cs2-instadefuse
B3none/cs2-clutch-announce
arikitos/cs2-heroshift
```

Instaplant is opt-in.

```powershell
./update.ps1 -FetchLatest -IncludeOptional -Source instaplant -WhatIf
./update.ps1 -FetchLatest -IncludeOptional -Source instaplant
```

Useful scopes.

```powershell
./update.ps1 -FetchLatest -Mode retake
./update.ps1 -FetchLatest -Source clutch-announce
./update.ps1 -Mode heroshift
./update.ps1 -Component matchzy
./update.ps1 -SharedOnly
./update.ps1 -WhatIf
./update.ps1 -Force
./update.ps1 -NoRestart
./update.ps1 -KeepBackups 5
```

Set `GITHUB_TOKEN` when GitHub API rate limits are relevant.

```powershell
$env:GITHUB_TOKEN = "<token>"
./update.ps1 -FetchLatest
```

## Offline package workflow

Downloaded or internally built packages can be placed directly under their component inbox.

```text
installs/modes/faceit/matchzy/
installs/modes/retake/retakes/
installs/modes/retake/instadefuse/
installs/modes/retake/instaplant/
installs/modes/heroshift/heroshift/
installs/modes/warcraft/warcraft-classic/
installs/shared/clutch-announce/
```

Then run.

```powershell
./update.ps1 -WhatIf
./update.ps1
```

The updater performs the following transaction for each component.

1. Reads and validates `package-manifest.json`.
2. Rejects unsafe paths, duplicate entries and unsupported identities.
3. Verifies every declared file size and SHA256.
4. Selects the highest semantic version for each component.
5. Compares it with `manager/.../packages/<component>.json`.
6. Skips equal or older versions and leaves every ZIP untouched.
7. Extracts a newer package into an isolated staging directory.
8. Moves only that component's current roots into a timestamped backup.
9. Activates the staged roots and writes the new component marker.
10. Restores every moved root and the previous marker if any stage fails.
11. Removes lower-version ZIP files only after the new version is active.
12. Keeps the installed ZIP in `installs`.
13. Recreates `cs2-game` only when an active mode or shared runtime changed.

Updates are serialized by `manager/data/package-update.lock`.

## Package format

A normalized package contains a manifest and payload.

```text
package-manifest.json
payload/
  plugins/
  utils/
  gamedata/
```

Example component package.

```json
{
  "schemaVersion": 2,
  "packageType": "mode",
  "id": "retake",
  "component": "instadefuse",
  "name": "InstadefusePlugin",
  "version": "2.0.1",
  "payloadRoot": "payload",
  "installStrategy": "replace-roots",
  "installRoots": [
    "utils/InstadefusePlugin"
  ],
  "files": [
    {
      "path": "payload/utils/InstadefusePlugin/InstadefusePlugin.dll",
      "size": 123456,
      "sha256": "lowercase-sha256"
    }
  ]
}
```

`replace-roots` updates only the declared component roots. `replace-release` replaces the complete release directory and is used for self-contained mode distributions such as HeroShift.

Existing HeroShift archives with the original `package: HeroShift`, `version: vX.Y.Z` manifest and `addons` layout remain supported through a verified compatibility adapter.

See `installs/README.md` for the full package contract.

## Manual replacement

Runtime files may be replaced directly under.

```text
manager/modes/<mode>/release
manager/shared/components/<component>/release
```

Editable configuration remains under each mode's `config` directory.

After a manual replacement, restart the active mode. A manual change does not alter component markers, so a later managed update still compares against the last recorded version. Use `-Force` to deliberately reinstall a selected package.

## Framework compatibility

Every mode declares required Metamod and CounterStrikeSharp versions. The manager-wide source of truth is.

```text
manager/shared/frameworks/versions.json
```

The current pinned pair is.

```text
Metamod 2.0.0-git1410
CounterStrikeSharp 1.0.371
```

The framework pair is deliberately not controlled by `-FetchLatest`. A plugin release can depend on a newer CounterStrikeSharp API, so framework upgrades require an explicit compatibility change, rebuilding local plugins and a live smoke test.

Install or repair the pinned framework pair with.

```bash
docker compose --profile maintenance run --rm cs2-modinstaller
```

The installer writes.

```text
<CS2_DATA_PATH>/game/csgo/addons/.cs2-manager-versions.json
```

Normal mode startup refuses to deploy when a mode requirement, the manager contract and the installed framework marker disagree.

## Setup

1. Copy `.env.example` to `.env` and configure the token, RCON password, panel credentials, `CS2_DATA_PATH` and `MANAGER_PATH`.
2. Run an online fetch, or place initial packages under `installs`.
3. Run setup.

```powershell
./update.ps1 -FetchLatest -WhatIf
./setup.ps1 -FetchLatest
```

`setup.ps1 -FetchLatest` downloads and applies default upstream releases before continuing. Plain `setup.ps1` applies only pending local packages with `update.ps1 -NoRestart`, validates Compose, builds the maintenance image, creates the stopped game container and starts the panel.

On Linux.

```bash
manager/scripts/start.sh
```

The Linux start script reports pending ZIP files but does not mutate packages. Run `pwsh ./update.ps1` first when PowerShell is available, or prepare the release directories before starting.

## CS2 maintenance

The normal game container never runs SteamCMD. Base game update and validation run only through `cs2-updater` and require the exact confirmation phrase.

```bash
CS2_UPDATER_CONFIRM="UPDATE CS2" \\
  docker compose --profile maintenance run --rm cs2-updater
```

Supported updater modes are `update`, `validate` and `repair-metamod`.

## Deployment flow

1. The panel writes `manager/data/runtime/active-mode.json`.
2. `cs2-game` starts or restarts.
3. The runtime launcher verifies framework compatibility.
4. `mode_applier.py` validates required sources and skips missing optional mounts.
5. The complete next layer is staged.
6. Previous inventory-owned targets are removed.
7. The staged layer is installed and inventory is replaced atomically.
8. CS2 starts with the selected format, map and cfg files.
9. The panel waits for RCON and verifies required plugins.

Native modules such as RayTrace are never hot-unloaded.

## Backups and rollback

Package backups are stored per component.

```text
manager/backups/packages/<package-type>/<id>/<component>/<version>-<timestamp>/
```

Panel-managed configuration backups are stored separately.

```text
manager/backups/config/<mode-id>/
```

`update.ps1` keeps three package backups per component by default. Configure the count with `-KeepBackups`.

## Verification

Repository checks.

```bash
python -m unittest discover -s manager/tests -v
python -m py_compile \\
  manager/panel/app.py \\
  manager/panel/mode_defs.py \\
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

## Raspberry Pi 5 deployment

CS2 provides an x86-64 Linux dedicated server. On Raspberry Pi 5, `cs2-game` runs through FEX inside an ARM64 container. The panel remains a native ARM64 service, while the game installation and FEX data are persisted on an SSD.

The verified host layout is.

```text
Host                 Raspberry Pi 5, Raspberry Pi OS Lite 64-bit
Kernel               Raspberry Pi v8 kernel with 4 KiB pages
Project              /server/cs2-server
Game data            /mnt/cs2-data/server
FEX data             /mnt/cs2-data/fex-data
Game port            27015 TCP and UDP
Panel port           8080 TCP
```

### Kernel requirement

The default Pi 5 `kernel_2712` uses 16 KiB pages. CS2 x86-64 libraries fail to map under emulation with that page size. This deployment requires the v8 kernel with 4 KiB pages.

```bash
uname -r
getconf PAGE_SIZE
```

The expected page size is `4096`.

### SSD and environment

The verified deployment uses an ext4 SSD mounted at `/mnt/cs2-data`.

```bash
findmnt /mnt/cs2-data
df -hT /mnt/cs2-data

sudo mkdir -p /mnt/cs2-data/server /mnt/cs2-data/fex-data
sudo chown -R "$(id -u):$(id -g)" \
  /mnt/cs2-data/server \
  /mnt/cs2-data/fex-data
```

Configure the host paths in `.env`.

```dotenv
CS2_DATA_PATH=/mnt/cs2-data/server
MANAGER_PATH=/server/cs2-server/manager
```

Keep the GSLT, RCON password, optional game password and panel credentials only in `.env`. The file is excluded from Git.

### Build and initialize FEX

The Raspberry Pi runtime expects a local ARM64 FEX image named `cs2-fex-runtime:test`.

```bash
docker build \
  --platform linux/arm64 \
  --file Dockerfile.generic \
  --tag cs2-fex-runtime:test \
  'https://github.com/ayayrom/CS2-Server-ARM-Docker.git#main'

docker image inspect cs2-fex-runtime:test \
  --format '{{.Os}}/{{.Architecture}}'
```

The expected image platform is `linux/arm64`.

Bootstrap the FEX RootFS once. The temporary CS2 data mount prevents this step from changing the real game installation.

```bash
mkdir -p /tmp/cs2-fex-bootstrap-data

docker run --rm \
  --name cs2-fex-bootstrap \
  --platform linux/arm64 \
  --env CI_TEST_MODE=true \
  --env PUID="$(id -u)" \
  --env PGID="$(id -g)" \
  --volume /tmp/cs2-fex-bootstrap-data:/cs2-data \
  --volume /mnt/cs2-data/fex-data:/home/steam/.fex-emu \
  cs2-fex-runtime:test
```

Verify the emulated environment.

```bash
docker run --rm \
  --platform linux/arm64 \
  --user "$(id -u):$(id -g)" \
  --env HOME=/home/steam \
  --env FEX_ROOTFS=/home/steam/.fex-emu/RootFS/Ubuntu_22_04 \
  --volume /mnt/cs2-data/fex-data:/home/steam/.fex-emu \
  --entrypoint bash \
  cs2-fex-runtime:test \
  -lc 'FEXBash "uname -m && getconf PAGE_SIZE"'
```

The expected output is.

```text
x86_64
4096
```

### Raspberry Pi Compose override

Use a host-specific `compose.override.yml` to select the FEX runtime.

```yaml
services:
  cs2-game:
    platform: linux/arm64
    build:
      context: ./manager/runtime
      dockerfile: Dockerfile.fex
      args:
        FEX_BASE_IMAGE: cs2-fex-runtime:test
    image: cs2-manager-runtime:fex-rpi5
    environment:
      CS2_EXECUTOR: fex
      FEX_ROOTFS: /home/steam/.fex-emu/RootFS/Ubuntu_22_04
      STEAMCLIENT_PATH: /home/steam/.fex-emu/steamclient.so
      DOTNET_EnableWriteXorExecute: "0"
    volumes:
      - type: bind
        source: /mnt/cs2-data/fex-data
        target: /home/steam/.fex-emu

  cs2-updater:
    platform: linux/amd64

  cs2-modinstaller:
    platform: linux/amd64
```

`DOTNET_EnableWriteXorExecute=0` is required for CounterStrikeSharp in the tested FEX environment. The persistent FEX directory must also contain a compatible x86-64 Steam client library at `/mnt/cs2-data/fex-data/steamclient.so`.

Validate and build the runtime.

```bash
docker compose config --quiet
docker compose build cs2-game

docker image inspect cs2-manager-runtime:fex-rpi5 \
  --format '{{.Os}}/{{.Architecture}}'
```

### Start and verify

```bash
docker compose up -d --no-deps cs2-game

docker logs --since 5m cs2-game 2>&1 | grep -Ei \
  'Mode deployed|executor=|CounterStrikeSharp.API Loaded|SteamGameServer_Init|Connection to Steam|server started|fatal|segmentation'
```

A healthy launch includes messages equivalent to.

```text
Mode deployed: retake
executor=fex
CounterStrikeSharp.API Loaded Successfully
SteamGameServer_Init() OK
Connection to Steam servers successful
server started
```

Changing modes through the panel updates `manager/data/runtime/active-mode.json`, transactionally deploys the selected mode and recreates `cs2-game` through the same FEX runtime.

### Panel and network access

Expose port `27015` over TCP and UDP. For Internet access, forward both protocols from the router to the Raspberry Pi LAN address. Do not forward panel port `8080` directly to the Internet.

The Steam LAN browser may not discover the server through Docker bridge networking. Add it to Favorites or connect directly.

```text
connect <RASPBERRY_PI_LAN_IP>:27015
connect <PUBLIC_IP>:27015
```

The panel binds to `0.0.0.0` by default. Use an SSH tunnel, VPN or secured reverse proxy for remote administration. Setting `PANEL_BIND=0.0.0.0` exposes it to the local network and requires strong panel credentials.

### Raspberry Pi health checks

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
findmnt /mnt/cs2-data
vcgencmd measure_temp
vcgencmd get_throttled
```

`throttled=0x0` indicates that no throttling condition has been recorded since boot. Preserve `/mnt/cs2-data/fex-data` and the FEX image build instructions when planning recovery. The normal `cs2-game` runtime never invokes SteamCMD.

## Security properties

The panel binds to localhost by default. Use a VPN or secured reverse proxy for remote access.

Release assets, package paths and manifest paths are validated before extraction. Every payload file is verified by SHA256. Extraction never writes outside the selected staging directory.

Only inventory-owned mode targets are removed from the persistent server. Framework roots are reserved from mode manifests. The browser has no arbitrary shell or Docker command surface.
