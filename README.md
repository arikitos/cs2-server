# CS2 Manager

A Docker Compose stack for one Counter-Strike 2 dedicated server that runs one
of three game modes at a time. A local web panel controls start, stop, restart,
mode switching, server settings, passwords, RCON, players, logs and maintenance.
The browser is never given a host shell or arbitrary Docker access.

## Architecture

Normal game operation and game updates are strictly separated:

- `cs2-game` is the only game service and always starts the existing CS2 install.
  Its runtime image never invokes SteamCMD.
- `cs2-updater` is maintenance-only and is the only service allowed to run
  SteamCMD.
- Metamod and CounterStrikeSharp are installed once into the persistent CS2
  installation and are shared by every mode.
- A mode switch transactionally deploys only the selected mode layer and then
  restarts the same `cs2-game` container.

The persistent installation has three logical layers:

1. **Base layer** — CS2, Metamod and CounterStrikeSharp.
2. **Shared manager layer** — shared files such as `server.cfg` and
   `PanelBridge`.
3. **Active mode layer** — the exact files declared by the selected
   `manager/modes/<mode>/mode.json`.

`manager/runtime/mode_applier.py` stages the complete next layer before touching
the live tree. It removes only paths listed in the prior manager-owned inventory,
installs the next layer, and atomically records the result. A failed deployment
restores the previous layer. Unmanaged server plugins are not deleted.

The inventory is stored inside the persistent server installation:

```text
.cs2-manager/managed-files.json
```

## Project structure

| Path | Responsibility |
|---|---|
| `compose.yml` | Defines `cs2-game`, maintenance-only `cs2-updater` and `cs2-modinstaller`, plus the panel. |
| `.env.example` / `.env` | Host paths, GSLT, RCON password, panel credentials, ports and pinned runtime image. |
| `manager/runtime/` | No-SteamCMD runtime launcher and transactional mode applier. |
| `manager/updater/` | Isolated SteamCMD update/validate/Metamod-repair service. |
| `manager/panel/` | Flask control plane, manifest loading, lifecycle, RCON, players, logs and maintenance. |
| `manager/versions.json` | Pinned Metamod and CounterStrikeSharp runtime versions. |
| `manager/shared/` | Files deployed for every mode, currently `server.cfg` and `PanelBridge`. |
| `manager/modes/<id>/` | One self-contained manifest, cfg set, main plugin, utilities and editable configs per mode. |
| `manager/data/` | Server state, per-mode settings, active-mode state, secrets and audit logs. |
| `manager/scripts/` | Setup, migration, rollback, stop, smoke test and framework installer scripts. |
| `manager/backups/` | Timestamped configuration backups; never the full game install. |
| `server/` | Host CS2 installation (`CS2_DATA_PATH`), gitignored and persistent. |

## Modes

| UI name | Mode id | Main plugin | Mode-only utilities | Match formats |
|---|---|---|---|---|
| FaceIt | `faceit` | MatchZy | AutoReady | 5v5 (default), 2v2, 1v1 |
| Retake | `retake` | RetakesPlugin | Instadefuse, RetakesPluginShared | 5v4 (default), 4v3 |
| HeroShift | `heroshift` | HeroShift | RayTrace native module, RayTraceImpl, RayTraceApi | 5v5 (default), 2v2, 1v1 |

All three modes run in `cs2-game`. `PanelBridge` is declared as a shared utility
by every mode. RayTrace is declared only by HeroShift and is removed from the
managed tree before another mode starts.

### Framework compatibility

Every mode declares the same installed Metamod/CounterStrikeSharp runtime pair.
`manager/versions.json` is the manager-wide source of truth, and normal startup
refuses to deploy a mode if either its manifest or the installed-version marker
disagrees.

This is a runtime compatibility contract, not a claim that every plugin DLL was
compiled against the same CounterStrikeSharp API package. The checked-in MatchZy
build references API `1.0.342`, while RayTraceImpl references API `1.0.371`.
The post-deployment smoke test is therefore still required to prove that the
complete pinned binary set loads together on the current CS2 build.

### Shared server config

Every mode deploys the same `manager/shared/cfg/server.cfg` and executes it first.
The mode cfg then adds only mode-specific convars, and the generated
`panel_runtime.cfg` executes last so panel-managed hot settings win.

Exec order:

```text
server.cfg -> mode_<id>.cfg -> panel_runtime.cfg
```

### Match formats

Each manifest declares its own `settings.formats` list, and the panel offers
exactly those. A format owns the slot count and the game alias, and may carry
extra convars or a plugin-config patch:

| Mode | Format | Slots | Game alias | Also configures |
|---|---|---:|---|---|
| FaceIt | 5v5 / 2v2 / 1v1 | 10 / 4 / 2 | competitive / wingman / competitive | `matchzy_minimum_ready_required` |
| Retake | 5v4 / 4v3 | 9 / 7 | competitive | `RetakesPlugin.json` → `MaxPlayers`, `TerroristRatio` |
| HeroShift | 5v5 / 2v2 / 1v1 | 10 / 4 / 2 | competitive / wingman / competitive | — |

The slot count, start map and game alias are derived, not stored by hand: the
panel writes them into `active-mode.json`, and the launcher turns them into
`-maxplayers`, `+map` and `+game_alias`. A format change therefore needs a
container start or restart, which the panel labels as such.

Plugin-config patches are written into the mode's declared config file and, when
that mode is already running, synced into the live game tree by `mode-applier`.

## Mode manifests

A mode owns everything it needs:

```text
manager/modes/<mode-id>/
├── mode.json
├── cfg/
├── config/              # where applicable
├── plugins/<Main>/
├── gamedata/            # where applicable
└── utils/<Helper>/
```

The manifest declares:

- installed framework requirements;
- startup alias and cfg files;
- match formats, and the settings defaults behind them;
- plugin, utility, shared-library, gamedata and config deployment targets;
- required-plugin health aliases;
- whitelisted RCON quick actions.

Sources must remain inside the mode folder or `manager/shared/`. Relative targets
are restricted to `addons/` and `cfg/` under `game/csgo`. Explicit absolute
targets are restricted to `/addons/`, which is required by RayTrace's native
gamedata lookup. Traversal, symlink sources, reserved framework roots,
conflicting targets and unsafe cfg/RCON commands are rejected.

To add a plugin, place it under the mode's `plugins/` or `utils/` directory and
add its source/target entry to `mode.json`. No Compose mount is added. Restart the
panel so it reloads the manifest, verify mounts, then restart/switch the mode.

## Mode switch flow

1. The panel validates saved mode settings and writes
   `manager/data/runtime/active-mode.json` atomically.
2. The same `cs2-game` container is started or restarted.
3. The launcher verifies the base game and installed framework marker.
4. The mode applier validates all sources and stages the complete next layer.
5. Only prior inventory-owned targets are moved out of the live tree.
6. The staged layer is installed and the inventory is atomically replaced.
7. The launcher templates `server.cfg` and starts CS2 with the selected alias,
   capacity, map and cfg files.
8. The panel waits for RCON and verifies required plugins.
9. If a switched-to mode does not become ready, the panel restores the previous
   active-mode state and restarts the previous mode.

Mode switching always restarts the game process. Native modules such as RayTrace
are never hot-unloaded.

## Setup

1. Copy `.env.example` to `.env` and configure:
   `SRCDS_TOKEN`, `CS2_RCON_PASSWORD`, `PANEL_USERNAME`, `PANEL_PASSWORD`,
   `CS2_DATA_PATH` and `MANAGER_PATH`.
2. Install/update base CS2 with the maintenance updater.
3. Install the pinned Metamod and CounterStrikeSharp pair:

   ```bash
   docker compose --profile maintenance run --rm cs2-modinstaller
   ```

4. Repair and validate the Metamod search path.
5. Create the stopped game container and start the panel:

   ```bash
   manager/scripts/start.sh
   ```

   On Windows:

   ```powershell
   ./setup.ps1
   ```

6. Open the panel at `http://127.0.0.1:8080`, select a mode and start it.

### Prerequisites

- Docker Desktop or Docker Engine with the Compose plugin.
- A writable CS2 dedicated-server installation at `CS2_DATA_PATH`.
- A Steam Game Server Login Token for a public server.
- Metamod and CounterStrikeSharp installed by the pinned installer before the
  first mode start.

## Operating

The panel exposes three focused areas:

1. **Status** — `cs2-game` state, active mode, match format, endpoint,
   visibility and plugin health.
2. **Lobby Setup** — one stacked form, in this order:
   1. *Game Mode* — FaceIt, Retake or HeroShift.
   2. *Match Format* — only the formats the selected mode declares.
   3. *Server Configuration* — focused groups for hostname, server password,
      timing and economy. Empty server password means public. Capacity, team
      behavior and bot quota stay derived from the selected format.
   4. *Friendly Fire* — On, Nades Only or Off. Damage scaling and team-kill
      punishment use the competitive defaults.
   5. *Map Pool* — the maps the lobby uses; the one marked `START` is the launch
      map, and each pooled map gets a one-click switch button while running.

   The lifecycle actions are **Start Server**, **Stop Server** and
   **Reset & Stop**. Reset restores the selected mode defaults, clears the
   server password and stops the game container.
3. **Server Console** — an approved RCON command line plus the running mode's
   plugin commands and relevant server commands. Selecting a command without an
   argument runs it immediately; commands with a `<placeholder>` are loaded for
   completion. The player list and the fixed `cs2-game` log stream live below it.

Freeze time, warmup time, rounds, round time, bots, overtime and friendly fire
apply live over RCON. Match format applies on the next start or restart, because
it changes `-maxplayers` and `+game_alias`. A start-map change uses `changelevel`.
Switching the selected mode restarts `cs2-game` and disconnects players.
It also clears the panel's bounded console history. Docker rotates `cs2-game`
logs at 10 MB with three retained files and panel logs at 5 MB with two retained
files; the panel never deletes Docker's active internal log files.

Server password is server-wide. Applying a value enables `sv_password` live over
RCON, while applying an empty value makes the server public. Passwords are
stored server-side and never returned by the API.

HeroShift v1.0.0 uses the single manager-owned `heroshift.json` override file.
The panel reload action synchronizes that file transactionally and issues
`css_reload` when HeroShift is active. Legacy `config.json` and
`skillsInfo.json` files are not deployed.

The verified HeroShift release is stored as a versioned local overlay rather
than duplicated inside the tracked mode tree. Fresh runs of `setup.ps1` and
`manager/scripts/start.sh` stage the bundled v1.0.0 package automatically.
Existing installations can run the matching installer under `manager/scripts`
to verify, back up, deploy, and activate the new overlay.

## Updating CS2 and frameworks

SteamCMD runs only in `cs2-updater` and requires the exact confirmation phrase:

```bash
CS2_UPDATER_CONFIRM="UPDATE CS2" \
  docker compose --profile maintenance run --rm cs2-updater
```

Other updater modes are `validate` and `repair-metamod`.

`manager/scripts/install-mods-linux.sh` resolves the exact framework versions
from `manager/versions.json`; it never follows a `latest` release. After
installation it writes:

```text
game/csgo/addons/.cs2-manager-versions.json
```

Changing framework versions is a deliberate compatibility operation: update
`manager/versions.json`, every mode's `requires` block, rebuild/retest in-house
plugins, and run the full live smoke test.

### Bootstrapping an empty installation

```bash
# 1. Install base CS2.
CS2_UPDATER_CONFIRM="UPDATE CS2" \
  docker compose --profile maintenance run --rm cs2-updater

# 2. Install pinned Metamod + CounterStrikeSharp.
docker compose --profile maintenance run --rm cs2-modinstaller

# 3. Restore the Metamod gameinfo.gi search path and validate.
CS2_UPDATER_MODE=repair-metamod CS2_UPDATER_CONFIRM="UPDATE CS2" \
  docker compose --profile maintenance run --rm cs2-updater
```

## Migration and rollback

Migrate from the old three-container topology only after reviewing the diff:

```powershell
./manager/scripts/migrate.ps1
```

The migration creates a timestamped configuration backup, removes only the known
old game containers, builds `cs2-game`, creates it stopped and recreates the
panel. It does not delete the persistent CS2 installation.

Rollback:

```powershell
./manager/scripts/rollback.ps1 `
  -Backup manager\backups\pre-single-runtime-YYYYMMDD-HHMMSS
```

Before restoring the old topology, rollback stops `cs2-game` and invokes the
mode applier's transactional `cleanup` operation. Only inventory-owned paths are
removed; unmanaged plugins remain. Removing the container also discards the
container-local absolute RayTrace `/addons` path.

## Verification

Repository checks:

```bash
python -m unittest discover -s manager/tests -v
python -m py_compile \
  manager/panel/app.py \
  manager/panel/mode_defs.py \
  manager/runtime/mode_applier.py
bash -n manager/runtime/runtime-launcher.sh
bash -n manager/scripts/start.sh
bash -n manager/scripts/stop.sh
bash -n manager/scripts/install-mods-linux.sh
bash -n manager/scripts/install-heroshift-release.sh
bash -n manager/scripts/smoke-test.sh
```

After deployment on a real server:

```bash
manager/scripts/smoke-test.sh
```

The smoke test checks one game container, no SteamCMD during normal operation,
mode isolation, RayTrace deployment/removal, capacity validation and manifest/
framework health.

## Security notes

- The panel binds to `127.0.0.1` by default. Use a VPN or secured reverse proxy
  for remote access; do not expose Basic Auth directly to an untrusted network.
- The browser receives no arbitrary shell or Docker command surface.
- RCON commands are classified and blocked/confirmed according to impact.
- GSLT, RCON and server passwords are redacted and never returned by the API.
- Only inventory-owned mode targets are removed.
- Base Metamod and CounterStrikeSharp directories are reserved and cannot be
  claimed by a mode manifest.
- SteamCMD remains an explicit maintenance-only path.
