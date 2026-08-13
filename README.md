# CS2 Server

A simple Docker Compose stack for one persistent Counter-Strike 2 server and one active game mode. The panel manages the existing server process. SteamCMD runs only as a separate maintenance job.

## Repository layout

```text
panel/                 Dashboard backend and current web UI
modes/                 Self-contained mode overlays
server/
  config/              Default server.cfg
  frameworks/          Pinned Metamod and CounterStrikeSharp installer
  runtime/             Game image and transactional mode manager
  state/               Operator settings, generated cfg files and inventories
  updater/             SteamCMD maintenance image
setup.ps1              First installation and safe reconfiguration
compose.yml            Runtime topology
```

Development files such as tests and workflows do not participate in the runtime layout.

## Mode contract

Each directory under `modes` mirrors paths below the CS2 `game/csgo` directory.

```text
modes/<mode>/
  mode.json
  addons/
  cfg/
```

There are no package inboxes, release bridges, mount lists or extraction adapters. On activation, every file below `addons` and `cfg` is copied automatically. Companion plugins belong in the same mode tree and are deployed in exactly the same way.

For example.

```text
modes/retakes/addons/counterstrikesharp/plugins/RetakesPlugin/
modes/retakes/addons/counterstrikesharp/plugins/InstadefusePlugin/
modes/retakes/addons/counterstrikesharp/plugins/PanelBridge/
```

`mode.json` contains only panel metadata, framework requirements, settings, commands and the expected plugin paths. It does not describe individual files or copy operations.

## Supported modes

| Directory | Main plugin | Bundled companions |
|---|---|---|
| `matchzy` | MatchZy | AutoReady, PanelBridge, ClutchAnnounce |
| `retakes` | RetakesPlugin | RetakesPluginShared, Instadefuse, PanelBridge, ClutchAnnounce |
| `heroshift` | HeroShift | RayTrace, PanelBridge, ClutchAnnounce |
| `warcraft` | WarcraftClassic | PanelBridge, ClutchAnnounce |

Metamod and CounterStrikeSharp are shared foundations. Their pinned versions live in `server/frameworks/versions.json` and are installed once into the persistent server directory.

## First setup

Requirements are Docker with Compose and PowerShell 7 or newer.

```powershell
./setup.ps1
```

The setup script performs the following operations.

1. Creates `.env` with absolute paths and random panel and RCON passwords.
2. Creates the persistent server and state directories.
3. Installs CS2 through the isolated SteamCMD service when needed.
4. Installs the pinned Metamod and CounterStrikeSharp versions.
5. Builds the game and panel images.
6. Starts only the panel. The game remains stopped until a mode is selected.

The panel binds to `127.0.0.1` by default. Set `PANEL_BIND` deliberately if it must be reachable from another host.

For an existing installation, set `CS2_DATA_PATH` in `.env` before rerunning setup. The operation is idempotent. Optional switches are available for controlled recovery.

```powershell
./setup.ps1 -SkipGameInstall
./setup.ps1 -SkipFrameworkInstall
```

## Updating or replacing a plugin

Stop the active game from the panel, then replace the plugin directory inside its mode with the files from the upstream release. Keep the upstream relative paths.

For a MatchZy release that contains `addons` and `cfg`, merge those two directories directly into `modes/matchzy`. For a companion plugin, merge its `addons` directory into the same mode. No manifest generation or update script is required.

After replacement, start the mode from the panel. The mode manager validates the layout and framework versions, stages every file, switches atomically and writes `server/state/runtime/mode-inventory.json`.

When switching modes, only files from the previous inventory are removed. Steam files, frameworks and plugin-created files that were not copied from a mode are preserved. If an unmanaged file conflicts with a mode file, activation stops with an explicit error instead of overwriting it.

## Configuration ownership

`server/config/server.cfg` is the tracked default and is loaded on every start. Panel changes are written as generated overrides under `server/state`, so updating a mode does not overwrite operator settings.

Editable plugin configuration is seeded from the mode on first use and then stored under.

```text
server/state/configs/<mode>/<original target path>
```

The generated runtime cfg files, active mode state, deployment inventory, audit data and backups also live under `server/state`. This directory is ignored by Git except for its placeholder.

## Maintenance

Update or validate the base CS2 installation from the panel. The backend stops the game, runs the dedicated updater container, repairs the Metamod search path, validates the installation and restores the previously selected mode.

Manual equivalents are.

```bash
CS2_UPDATER_CONFIRM="UPDATE CS2" docker compose --profile maintenance run --rm cs2-updater
docker compose --profile maintenance run --rm cs2-modinstaller
```

SteamCMD is not present in the live game workflow. The runtime launcher fails clearly if the base game, active mode state, runtime cfg or required framework version is missing.

## Transaction and migration behavior

The mode manager inventories individual files with SHA256 values. Deployment is staged before the live tree changes. Existing managed files are moved to a transaction backup, the new set is installed, and any failure restores the previous set.

The first activation after upgrading from the old directory-based inventory keeps a permanent copy under `server/state/backups/legacy-mode-layout-<timestamp>`. This is the only migration backup that may contain old generated files.

## Development verification

```bash
python3 -m unittest discover -s server/tests -v
python3 -m py_compile panel/*.py server/runtime/mode_manager.py
bash -n server/runtime/runtime-launcher.sh server/frameworks/install-linux.sh server/updater/updater.sh
```

A live smoke test is available after setup.

```bash
PANEL_AUTH='admin:<password>' ./server/scripts/smoke-test.sh
```
