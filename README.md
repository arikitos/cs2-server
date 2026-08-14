# CS2 Server for Windows

A local Docker Desktop stack for one persistent Counter-Strike 2 server and one active game mode. A fresh Windows clone can be installed by double-clicking `run-setup.cmd`. The panel manages the existing server process, while SteamCMD runs only as a separate maintenance job.

The Windows host runs Linux containers through Docker Desktop. The dedicated server files under `server/cs2` are therefore the Linux depot expected by the runtime container, not a native Windows CS2 installation.

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
run-setup.cmd    Double-click Windows installer
setup.ps1   Windows bootstrap and safe reconfiguration
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

## First setup on Windows

Install Git and Docker Desktop, then make sure Docker Desktop is configured to use Linux containers. Clone the repository and double-click.

```text
run-setup.cmd
```

The launcher uses the Windows PowerShell included with Windows, bypasses the local script execution policy only for this installation process, and starts Docker Desktop automatically when it is installed but not running.

The setup script performs the following operations.

1. Verifies that the host is Windows and Docker Desktop is running Linux `amd64` containers.
2. Creates `.env` with absolute paths and random panel and RCON passwords.
3. Creates the persistent server and state directories.
4. Installs CS2 into `server/cs2` through the isolated SteamCMD service when needed.
5. Installs the pinned Metamod and CounterStrikeSharp versions.
6. Builds the game and panel images.
7. Starts only the panel. The game remains stopped until a mode is selected.

The panel binds to `127.0.0.1` by default. Set `PANEL_BIND` deliberately if it must be reachable from another host.

Rerunning `run-setup.cmd` preserves the generated passwords and an existing `CS2_DATA_PATH`. If the CS2 binary is already present, SteamCMD does not download the game again. The repository path is refreshed automatically so a moved clone keeps using its current modes and configuration.

For a server installation outside the repository, set `CS2_DATA_PATH` in `.env` before rerunning setup. Optional recovery switches can be passed directly to the PowerShell script.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\setup.ps1 -SkipGameInstall
powershell.exe -ExecutionPolicy Bypass -File .\setup.ps1 -SkipFrameworkInstall
```

## Updating or replacing a plugin

Stop the active game from the panel, then replace the plugin directory inside its mode with the files from the upstream release. Keep the upstream relative paths.

For a MatchZy release that contains `addons` and `cfg`, merge those two directories directly into `modes/matchzy`. For a companion plugin, merge its `addons` directory into the same mode. No manifest generation or update script is required.

After replacement, start the mode from the panel. The mode manager validates the layout and framework versions, stages every file, switches atomically and writes `server/state/runtime/mode-inventory.json`.

When switching modes, only files from the previous inventory are removed. Steam files, frameworks and plugin-created files that were not copied from a mode are preserved. If an unmanaged file conflicts with a mode file, activation stops with an explicit error instead of overwriting it.

## Configuration ownership

`server/config/server.cfg` is the tracked default and is loaded on every start. Panel changes are written as generated overrides under `server/state`, so updating a mode does not overwrite operator settings.

Each mode declares its visible panel controls in `settings.panel.controls`. The backend enforces the same policy, so hiding a field is not merely a UI decision.

| Mode | Panel controls | Plugin configuration behavior |
|---|---|---|
| MatchZy | Start, stop, status, players, logs and official commands | MatchZy cfg files are upstream-owned and operator overrides are ignored |
| Retakes | Format, hostname, password and map pool | `RetakesPlugin.json` receives the selected format on Start, while the plugin-generated `cfg/cs2-retakes/retakes.cfg` owns gameplay convars |
| HeroShift | Format, server gameplay, friendly fire and map pool | `heroshift.json` remains separate operator state and supports the official `css_reload` action |
| Warcraft Classic | Format, server gameplay, friendly fire and map pool | `WarcraftClassic.json` is loaded at plugin startup and requires Start or Restart after changes |

The Start action sends the selected mode settings and starts or restarts the game in one request. Settings that are not declared as panel controls are normalized to the mode defaults and are not emitted into `panel_runtime.cfg`.

Editable plugin configuration is seeded from the mode on first use and then stored under.

```text
server/state/configs/<mode>/<original target path>
```

A config declaration may set `editable` to `false`. Such a file is always deployed from the mode release, and a legacy file under `server/state/configs` cannot override it.

The generated runtime cfg files, active mode state, deployment inventory, audit data and backups also live under `server/state`. This directory is ignored by Git except for its placeholder.

## Maintenance

Update or validate the base CS2 installation from the panel. The backend stops the game, runs the dedicated updater container, repairs the Metamod search path, validates the installation and restores the previously selected mode.

Manual PowerShell equivalents are.

```powershell
docker compose --profile maintenance run --rm -e "CS2_UPDATER_CONFIRM=UPDATE CS2" cs2-updater
docker compose --profile maintenance run --rm cs2-modinstaller
```

SteamCMD is not present in the live game workflow. The runtime launcher fails clearly if the base game, active mode state, runtime cfg or required framework version is missing.

## Transaction and migration behavior

The mode manager inventories individual files with SHA256 values. Deployment is staged before the live tree changes. Existing managed files are moved to a transaction backup, the new set is installed, and any failure restores the previous set.

The first activation after upgrading from the old directory-based inventory keeps a permanent copy under `server/state/backups/legacy-mode-layout-<timestamp>`. This is the only migration backup that may contain old generated files.

## Development verification

The Python checks run directly on any development host with Python. Shell syntax checks run in CI or a Linux development shell.

```bash
python3 -m unittest discover -s server/tests -v
python3 -m py_compile panel/*.py server/runtime/mode_manager.py
bash -n server/runtime/runtime-launcher.sh server/frameworks/install-linux.sh server/updater/updater.sh
```

A live smoke test is available after setup.

```bash
PANEL_AUTH='admin:<password>' ./server/scripts/smoke-test.sh
```
