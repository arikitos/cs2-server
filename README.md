# CS2 Server Manager for Windows

A local Docker Desktop stack for one persistent Counter-Strike 2 dedicated server, one active game process, and one active game mode.

The project installs the Linux CS2 dedicated server depot on a Windows host, keeps the large server installation outside the container filesystem, and uses self-contained mode directories for MatchZy, Retakes, HeroShift, and Warcraft Classic.

## Supported platform

The current branch supports one deployment target.

- Windows on an `amd64` or `x86_64` computer.
- Docker Desktop running Linux containers.
- A local persistent CS2 installation managed through bind mounts.

Raspberry Pi, ARM, FEX emulation, and a native Linux host installer are not part of the current runtime contract.

## Core doctrine

- One Steam installation is shared by every mode.
- Only one `cs2-game` process and one mode may be active at a time.
- SteamCMD never runs inside the live game workflow.
- Every mode keeps the upstream `addons` and `cfg` layout.
- Companion plugins belong inside the mode that consumes them.
- Metamod and CounterStrikeSharp are shared server foundations, not mode payloads.
- Release files and operator owned state remain separate.
- The panel exposes only settings owned by the selected mode.
- Backend validation enforces the same ownership policy as the user interface.
- Mode activation is transactional and removes only files recorded in the previous managed inventory.
- Direct edits inside the deployed `server/cs2/game/csgo` tree are not part of the supported workflow.

## Included modes

| Mode | Main plugin | Bundled companions | Upstream source |
|---|---|---|---|
| MatchZy | MatchZy | AutoReady, PanelBridge, ClutchAnnounce | [shobhit-pathak/MatchZy](https://github.com/shobhit-pathak/MatchZy) |
| Retakes | RetakesPlugin | RetakesPluginShared, RetakesAllocator, Instadefuse, PanelBridge, ClutchAnnounce | [B3none/cs2-retakes](https://github.com/B3none/cs2-retakes) |
| HeroShift | HeroShift | RayTrace, PanelBridge, ClutchAnnounce | [arikitos/cs2-heroshift](https://github.com/arikitos/cs2-heroshift) |
| Warcraft Classic | WarcraftClassic | PanelBridge, ClutchAnnounce | [arikitos/cs2-warcraft3](https://github.com/arikitos/cs2-warcraft3) |

The Retakes mode contains a customized build of [yonilerner/cs2-retakes-allocator](https://github.com/yonilerner/cs2-retakes-allocator). Its source and design notes are stored under `plugins-src/retakes-allocator`.

## Runtime architecture

| Service | Responsibility | Normal state |
|---|---|---|
| `cs2-game` | Runs the single CS2 dedicated server and deploys the selected mode before launch | Stopped until Start is selected in the panel |
| `panel` | Provides the dashboard, authenticated API, RCON control, state management, logs, and Docker orchestration | Running after setup |
| `cs2-updater` | Runs SteamCMD update, validation, and Metamod repair operations | Created only for maintenance |
| `cs2-modinstaller` | Installs the pinned Metamod and CounterStrikeSharp versions | Created only for setup or repair |

The panel mounts the Docker socket because it controls the game and maintenance containers. Treat access to the panel as administrator access to the local Docker host.

## Repository layout

```text
.
├── panel/
│   ├── app.py                     Dashboard backend and API
│   ├── mode_defs.py               Mode manifest validation
│   ├── config_guard.py            Post start configuration replay and rollback
│   ├── maintenance_guard.py       SteamCMD and repair safeguards
│   ├── templates/                 Dashboard page
│   └── static/                    Dashboard styles
├── modes/
│   ├── matchzy/                   MatchZy release tree and companions
│   ├── retakes/                   Retakes release tree and companions
│   ├── heroshift/                 HeroShift release tree and companions
│   └── warcraft/                  Warcraft Classic release tree and companions
├── plugins-src/
│   └── retakes-allocator/         Customized RetakesAllocator source and tests
├── server/
│   ├── config/server.cfg          Shared server configuration template
│   ├── cs2/                       Persistent Steam installation, created locally
│   ├── frameworks/                Pinned framework definitions and installer
│   ├── runtime/                   Runtime image, launcher, and mode manager
│   ├── state/                     Operator state, generated files, backups, and audit data
│   ├── updater/                   SteamCMD maintenance image
│   ├── scripts/                   Operational and smoke test scripts
│   └── tests/                     Python unit and repository contract tests
├── .github/workflows/             CI and RetakesAllocator build workflows
├── .env.example                   Environment template
├── compose.yml                    Docker Compose topology
├── run-setup.cmd                  Double click Windows installer
└── setup.ps1                      Windows setup implementation
```

`server/cs2`, `server/state`, and `.env` are intentionally excluded from Git.

## Persistent storage and path mapping

The CS2 installation is physically stored on the Windows host. By default it is created here.

```text
<repository>/server/cs2
```

The setup script writes absolute Windows host paths into `.env`.

```env
PROJECT_PATH=C:/Users/<username>/cs2-server
CS2_DATA_PATH=C:/Users/<username>/cs2-server/server/cs2
```

Docker Compose maps those host paths into Linux paths used by the containers.

| Windows host path | Container path | Purpose |
|---|---|---|
| `${CS2_DATA_PATH}` | `/home/steam/cs2-dedicated` | Writable CS2 installation for the game and updater |
| `${PROJECT_PATH}/modes` | `/modes` | Read only mode release trees |
| `${PROJECT_PATH}/server/state` | `/state` or `/data` | Persistent operator and runtime state |
| `${PROJECT_PATH}/server/config` | `/server-config` | Shared `server.cfg` source |
| `${PROJECT_PATH}/server/frameworks` | `/frameworks` | Framework versions and installer |
| `${PROJECT_PATH}` | `/project` | Read only project source for panel operations |

`CS2_DATA_PATH` and `PROJECT_PATH` must contain host paths. They must not contain paths that exist only inside a container.

This design preserves the server installation when containers are rebuilt or removed, and allows SteamCMD, the game runtime, and the panel to operate on the same persistent files.

## Requirements

- Git for Windows.
- Docker Desktop with Docker Compose.
- Docker Desktop configured for Linux containers.
- An `amd64` or `x86_64` Docker engine.
- Sufficient free disk space for the CS2 dedicated server and future updates.
- TCP and UDP port `27015` available for the game, unless changed in `.env`.
- TCP port `8080` available on localhost for the panel, unless changed in `.env`.

## First installation

Clone the repository.

```powershell
git clone https://github.com/arikitos/cs2-server.git
cd cs2-server
```

Optional preconfiguration can be done before the first setup.

```powershell
Copy-Item .env.example .env
notepad .env
```

Values left empty for `PROJECT_PATH`, `CS2_DATA_PATH`, `PANEL_PASSWORD`, and `CS2_RCON_PASSWORD` are filled automatically by the setup script.

Start the installer by double clicking `run-setup.cmd`, or run it from a terminal.

```powershell
.\run-setup.cmd
```

The installer performs these operations.

1. Confirms that the host is Windows.
2. Confirms that Docker Desktop and Docker Compose are available.
3. Starts Docker Desktop when it is installed but not running.
4. Rejects Windows containers and non-`amd64` Docker engines.
5. Creates or updates `.env` with absolute host paths.
6. Generates panel and RCON passwords when they are missing.
7. Creates the persistent CS2 and state directories.
8. Validates the Docker Compose configuration.
9. Builds the maintenance images.
10. Downloads the CS2 dedicated server through the isolated SteamCMD service when the game binary is missing.
11. Installs the pinned Metamod and CounterStrikeSharp versions.
12. Builds the game and panel images.
13. Starts the panel and leaves `cs2-game` stopped.

After setup, open the panel.

```text
http://127.0.0.1:8080
```

Use `PANEL_USERNAME`, which defaults to `admin`, and the generated `PANEL_PASSWORD` stored in `.env`.

Select a mode in the dashboard and press Start. The first game launch begins only after a mode has been selected.

## Daily operation

1. Start Docker Desktop.
2. Open `http://127.0.0.1:8080`.
3. Select MatchZy, Retakes, HeroShift, or Warcraft Classic.
4. Change only the settings exposed for that mode.
5. Press Start to save the pending settings, deploy the mode, and launch the server.
6. Use the same dashboard for status, players, approved commands, current-session logs, restart, and stop operations.

Only one mode can run at a time. Selecting another mode and pressing Start stops the current game process, transactionally replaces its managed payload, and starts the new mode.

## Updating an existing checkout

Stop the game from the panel, update the repository, and rerun setup.

```powershell
git pull --ff-only
.\run-setup.cmd
```

This preserves `.env`, `server/state`, and the existing CS2 installation. The installer rebuilds the local images and recreates the managed containers. It downloads the complete game only when the expected CS2 binary is missing.

## Repeating or repairing setup

Running `run-setup.cmd` again preserves an existing `CS2_DATA_PATH`, panel password, and RCON password. The current repository path is refreshed automatically.

SteamCMD does not download the complete server again when the expected CS2 binary already exists.

The PowerShell installer also supports these recovery options.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\setup.ps1 -SkipGameInstall
powershell.exe -ExecutionPolicy Bypass -File .\setup.ps1 -SkipFrameworkInstall
```

Use `SkipGameInstall` only when a valid Linux CS2 dedicated server already exists at `CS2_DATA_PATH`.

## Environment configuration

| Variable | Default or setup behavior | Responsibility |
|---|---|---|
| `SRCDS_TOKEN` | Empty | Steam game server login token passed to the game runtime |
| `CS2_SERVERNAME` | Empty | Initial server name and the source value used by the shared server template |
| `CS2_PASSWORD` | Empty | Initial game password, panel state becomes authoritative after first use |
| `CS2_RCON_PASSWORD` | Generated when empty | RCON authentication used by the panel and game |
| `CS2_PORT` | `27015` | Published TCP and UDP game port |
| `CS2_TV_ENABLE` | `0` | Enables CSTV explicitly. Keep disabled for one visible LAN server |
| `CS2_TV_PORT` | `27020` | Internal CSTV port, not published separately by the current Compose file |
| `CS2_BASE_IMAGE` | Pinned image digest | Base image used by runtime and maintenance builds |
| `CS2_UPDATER_MODE` | `update` | Default maintenance operation |
| `CS2_UPDATER_CONFIRM` | Empty | Confirmation guard for direct maintenance use |
| `CS2_DATA_PATH` | `<repository>/server/cs2` | Absolute Windows host path for the persistent server installation |
| `PROJECT_PATH` | Repository root | Absolute Windows host path for bind mounts and panel orchestration |
| `PANEL_USERNAME` | `admin` | Panel Basic authentication username |
| `PANEL_PASSWORD` | Generated when empty | Panel Basic authentication password |
| `PANEL_PORT` | `8080` | Host port for the panel |
| `PANEL_BIND` | `127.0.0.1` | Host interface used by the panel |
| `CS2_ALLOWED_MAPS` | Active competitive map list | Optional comma-separated map allowlist |

Rerun setup after changing values that are injected into container definitions, so Docker Compose can recreate containers with the new environment.

## CSTV, MatchZy demos, and duplicate LAN entries

CSTV is a second server endpoint used for spectators and demo recording. When it is enabled, CS2 can show both the game server and the CSTV endpoint in the LAN browser. This is not a second `cs2-game` container.

The default configuration keeps CSTV disabled and MatchZy does not force it on. This produces one game server entry under normal operation.

To enable MatchZy demo recording deliberately, set this value in `.env`.

```env
CS2_TV_ENABLE=1
```

Rerun `run-setup.cmd` to recreate the game container with the new environment, then start MatchZy from the panel. A separate CSTV entry may be visible while CSTV is enabled.

The current Compose topology does not publish `CS2_TV_PORT` to the Windows host. CSTV can therefore support server-side MatchZy recording, but direct spectator connections to port `27020` are not part of the default setup.

## What the panel manages

The current dashboard exposes these areas.

- Server and container status.
- RCON readiness, Metamod health, CounterStrikeSharp health, required plugin health, map, and player count.
- Mode selection and mode specific settings.
- Start, stop, restart through mode Start, and reset operations.
- Public or password protected server visibility.
- An approved RCON command catalog for the active mode.
- Current player information with Kick and temporary or permanent Ban actions.
- Active game logs with pause, refresh, and automatic scrolling.
- Live map switching when the active mode allows panel managed map selection.
- Pending change previews that identify live changes, map reloads, and restart changes.

The panel backend also contains authenticated API operations for these tasks.

- CS2 update and validation through an isolated SteamCMD container.
- Metamod search path repair.
- Configuration state backup and restore.
- Mode payload verification.
- Audit log access.
- Panel rebuild and restart.

The current web page focuses on status, lobby setup, commands, players, and game logs. Some maintenance operations are currently API only.

The server console is not an unrestricted shell and it is not a live SteamCMD terminal. It accepts only server and plugin commands declared in the approved catalog for the active mode. Process termination commands and arbitrary command chaining are rejected.

## Configuration ownership by mode

The panel uses the `settings.panel.controls` declaration in every `mode.json` file. Hidden settings are also rejected or normalized by the backend, so the ownership boundary is not only visual.

| Mode | Panel editable settings | Plugin owned settings | Apply behavior |
|---|---|---|---|
| MatchZy | No gameplay configuration. Lifecycle, health, players, logs, and official MatchZy commands remain available | Match flow, ready requirements, warmup, knife, live, overtime, economy, bots, and friendly fire | MatchZy uses its upstream configuration and stage files without panel gameplay overrides |
| Retakes | Format, hostname, game password, and map pool | Timing, rounds, economy, bots, friendly fire, autoplant, Instadefuse, and allocator loadouts | Format updates `RetakesPlugin.json` and applies on Start. Retakes executes `cfg/cs2-retakes/retakes.cfg` after map start |
| HeroShift | Format, hostname, game password, timing, economy, overtime, friendly fire, and map pool | HeroShift skill definitions and skill overrides in `heroshift.json` | CS2 values are panel managed. After changing an operator override, the plugin can reload it with the approved `css_reload` action |
| Warcraft Classic | Format, hostname, game password, timing, economy, overtime, friendly fire, and map pool | XP, races, skills, abilities, and persistence behavior in `WarcraftClassic.json` | CS2 values are panel managed. Plugin configuration requires Start or Restart |

Format selection also determines the game alias, slot capacity, and derived bot quota where the panel owns those values.

### Default gameplay profile differences

These are the relevant startup defaults in the tracked repository. MatchZy is intentionally marked as dynamic because its warmup, knife, live, overtime, and loaded match configuration can execute additional upstream stage files after startup.

| Mode | Default format | Rounds | Freeze | Warmup | Round time | Buy time | Money | Bots | Overtime | Authoritative source |
|---|---|---:|---:|---:|---:|---:|---|---|---|---|
| MatchZy | Upstream 5v5 flow | Dynamic | Dynamic | Dynamic | Dynamic | Dynamic | Dynamic | Upstream owned | Upstream owned | MatchZy config, match files, and stage files |
| Retakes | 4v3, 7 slots | 15 | 7 seconds | 30 seconds | 1.25 minutes | 0 seconds | Disabled | `bot_quota 0`, plugin managed | Off | `cfg/cs2-retakes/retakes.cfg` and Retakes plugin JSON |
| HeroShift | 5v5, 10 slots | 24 | 15 seconds | 20 seconds | 1.92 minutes | 20 seconds | 800 to 16000 | Derived from format | Off | Panel state and generated `panel_runtime.cfg` |
| Warcraft Classic | 5v5, 10 slots | 24 | 15 seconds | 20 seconds | 1.92 minutes | 20 seconds | 800 to 16000 | Derived from format | Off | Panel state and generated `panel_runtime.cfg` |

Retakes also provides a 5v4 format. HeroShift and Warcraft Classic provide 5v5, 2v2, and 1v1 formats. MatchZy contains upstream format metadata, but the panel does not expose format or gameplay editing for that mode.

## Configuration layers and startup order

The server uses separate layers instead of copying every mode setting into one shared file.

1. `server/config/server.cfg` provides the tracked shared template.
2. The selected mode contributes its complete `addons` and `cfg` payload.
3. Panel managed settings are generated under `server/state/runtime/<mode>/panel_runtime.cfg`.
4. The mode manager stages the desired files and atomically deploys them into `server/cs2/game/csgo`.
5. `mode_<mode>.cfg` executes the shared `server.cfg` and adds only mode bootstrap behavior.
6. `panel_runtime.cfg` applies only settings owned by the selected mode.
7. After RCON becomes ready, the configuration guard replays panel owned live values.
8. Plugins may execute their own stage or map configuration later, such as MatchZy match stages and the Retakes map start profile.

The shared template remains global. A mode must not include its own `cfg/server.cfg`.

## What can be edited

### Host and container settings

Edit `.env` for ports, bind address, server identity defaults, Steam token, Docker image pin, and persistent host paths. Do not commit `.env`.

### Mode settings in the panel

Use the selected mode tab for fields shown by that mode. Pressing Start sends pending settings, saves them, generates the runtime configuration, applies plugin format changes when required, and starts or restarts the game container in one request.

### Shared server template

Edit `server/config/server.cfg` only for truly global base behavior. Keep its template placeholders intact unless the corresponding runtime substitution is intentionally being removed.

### Plugin operator configuration

Editable plugin configurations use this operator state pattern.

```text
server/state/configs/<mode>/<original target path>
```

If an override exists, the mode manager deploys it instead of the release copy. If no override exists, the file from `modes/<mode>` is used.

Important editable targets include these files.

| Mode | Operator override target |
|---|---|
| Retakes | `server/state/configs/retakes/addons/counterstrikesharp/configs/plugins/RetakesPlugin/RetakesPlugin.json` |
| Retakes | `server/state/configs/retakes/addons/counterstrikesharp/plugins/RetakesAllocator/config/config.json` |
| HeroShift | `server/state/configs/heroshift/addons/counterstrikesharp/plugins/HeroShift/configs/heroshift.json` |
| Warcraft Classic | `server/state/configs/warcraft/addons/counterstrikesharp/configs/plugins/WarcraftClassic/WarcraftClassic.json` |

When an operator override does not exist yet, copy the corresponding file from the mode release tree while preserving the original relative path under `server/state/configs/<mode>`.

MatchZy `cfg/MatchZy/config.cfg` is declared with `editable` set to `false`. A legacy state copy cannot override the upstream file.

### Mode release payloads

Files under `modes/<mode>/addons` and `modes/<mode>/cfg` are tracked release sources. Replace them when updating a plugin release, while preserving manager files such as `mode.json` and `cfg/mode_<mode>.cfg`.

### Generated and deployed files

Do not edit these paths directly.

- `server/state/runtime/<mode>/panel_runtime.cfg`, because the panel regenerates it.
- `server/state/runtime/active-mode.json`, because it represents the selected runtime state.
- `server/state/runtime/mode-inventory.json`, because it is the transactional ownership record.
- Managed files below `server/cs2/game/csgo`, because the next mode activation may replace or remove them.

## Mode package contract

Each mode mirrors paths below the server `game/csgo` directory.

```text
modes/<mode>/
├── mode.json
├── addons/
└── cfg/
```

Every file below `addons` and `cfg` is copied automatically during activation. There are no release inboxes, mount lists, bridge directories, or per-file copy manifests.

`mode.json` declares these contracts.

- Mode identity and display metadata.
- Required Metamod and CounterStrikeSharp versions.
- Startup game alias and configuration filenames.
- Panel control ownership.
- Formats and defaults.
- Main plugins and mode local utilities.
- Editable or upstream owned plugin configuration files.
- Approved plugin commands.

Symbolic links, unsafe relative paths, missing plugin payloads, invalid manifests, and framework version mismatches are rejected before deployment.

## Transactional mode switching

Mode activation builds an inventory of individual files and their SHA256 values.

The manager performs these operations.

1. Validates the selected manifest, required frameworks, payload, runtime state, and configuration files.
2. Stages the complete desired file set on the CS2 installation filesystem.
3. Moves existing managed files into a transaction backup.
4. Installs the staged files atomically.
5. Writes `server/state/runtime/mode-inventory.json`.
6. Restores the previous files when deployment fails.

Only files recorded in the previous inventory are removed during a switch. Steam files, shared frameworks, plugin generated databases, and other unmanaged runtime data are preserved.

An unmanaged file that conflicts with a desired mode file blocks activation instead of being overwritten. Move the conflicting file or make it identical to the tracked mode source.

## Updating or replacing a mode plugin

1. Stop the active game from the panel.
2. Download the desired upstream release.
3. Merge its `addons` and `cfg` paths directly into the correct `modes/<mode>` directory.
4. Preserve `mode.json`, `cfg/mode_<mode>.cfg`, and mode local companion plugins that are not part of the upstream release.
5. Review upstream configuration changes before keeping an existing operator override.
6. Run the repository checks.
7. Start the mode from the panel.
8. Confirm RCON, framework health, required plugin health, players, and logs.

Updating one mode does not require copying files manually into `server/cs2`.

## Shared framework versions

Framework versions are pinned in `server/frameworks/versions.json`.

```text
Metamod 2.0.0-git1410
CounterStrikeSharp 1.0.371
```

Every mode declares the same required versions. The mode manager refuses to launch when the repository version or installed server version does not satisfy the selected manifest.

Install or repair the pinned pair with this command.

```powershell
docker compose --profile maintenance run --rm cs2-modinstaller
```

Do not update a shared framework without checking all four modes for API and binary compatibility.

## Customized RetakesAllocator

The Retakes mode uses an automatic five stage loadout sequence.

1. Round one uses team pistols and no primary weapon.
2. Round two uses a random team specific secondary and no primary weapon.
3. Round three uses a random SMG and team pistol.
4. Round four uses a random mid tier rifle and team pistol.
5. Round five and later use an AK47 for Terrorists, a random M4A4 or M4A1S for Counter Terrorists, team pistols, and one randomly assigned AWP across all active players.

The progression is configured through `RoundLoadoutSequence` in the allocator `config.json`. Weapon pools, round ranges, and preferred weapon limits can be changed without rebuilding the plugin.

Source changes under `plugins-src/retakes-allocator` are tested and built by `.github/workflows/build-retake-plugin.yml`. The workflow installs the deployable payload under the Retakes mode and commits generated plugin files back to `main`.

The customized source contains an intentional SQLite native bundle compatibility pin and its accepted security tradeoff. Read `plugins-src/retakes-allocator/ARIKITOS_CUSTOMIZATION.md` before changing SQLitePCLRaw, the target framework, or the Steam runtime compatibility strategy.

## Maintenance

SteamCMD operations are isolated from the running game process.

The maintenance workflow follows this order.

1. Creates a backup of manager configuration and state.
2. Stops `cs2-game`.
3. Runs the updater container with an explicit confirmation phrase.
4. Updates or validates the persistent Steam installation.
5. Repairs the Metamod search path when requested.
6. Restores the previously selected mode.
7. Waits for RCON readiness.

Manager backups do not copy the complete CS2 installation. They contain panel state, secrets state, mode settings, plugin configuration overrides, runtime state, and console history.

Manual maintenance commands are available when needed.

```powershell
docker compose --profile maintenance run --rm -e "CS2_UPDATER_CONFIRM=UPDATE CS2" cs2-updater
docker compose --profile maintenance run --rm cs2-modinstaller
```

## Logs and audit behavior

The game log view is session scoped. It returns logs from the active mode timestamp and does not display old game output when the game is stopped or no mode is selected.

The backend can also read panel, updater, audit, Docker, game, and filtered plugin log sources. Sensitive RCON passwords, game passwords, and Steam tokens are redacted from supported outputs.

Audit entries are stored as daily JSON Lines files under `server/state/audit`.

## Security notes

- `.env` contains secrets and is excluded from Git.
- `server/state` can contain passwords, command history, audit data, and plugin configuration, and is excluded from Git.
- The panel binds to `127.0.0.1` by default.
- Changing `PANEL_BIND` can expose an administrator interface that controls Docker through `/var/run/docker.sock`.
- Use a strong `PANEL_PASSWORD` and RCON password.
- Do not expose the panel directly to an untrusted network.
- Use a trusted reverse proxy and additional access controls if remote access is required.
- Back up `.env` and `server/state` securely.

## Current limitations

- The setup flow supports Windows and Docker Desktop only.
- Only one game container and one mode can run at a time.
- The current dashboard does not provide a generic JSON editor for every plugin configuration file.
- Team movement is not implemented without an additional plugin.
- Warcraft XP level grant and removal controls are not implemented in the current panel action catalog.
- The RCON console is allowlisted and does not accept arbitrary server commands.
- SteamCMD and some maintenance operations are controlled workflows, not an interactive terminal.
- CSTV spectator connections are not published by the default Compose topology.

## Troubleshooting

| Symptom | Check |
|---|---|
| Setup reports that Docker is missing | Install or update Docker Desktop and confirm that `docker` is available in the Windows PATH |
| Setup rejects the Docker engine | Switch Docker Desktop to Linux containers and confirm `amd64` architecture |
| CS2 binary is missing | Run `run-setup.cmd` without `SkipGameInstall` |
| A mode reports a framework mismatch | Rerun setup or run `cs2-modinstaller` with the maintenance profile |
| Metamod is missing from `gameinfo.gi` | Run the controlled Metamod repair operation |
| A mode reports an unmanaged file conflict | Move the conflicting deployed file or make it identical to the tracked mode source |
| RCON does not become ready | Check `CS2_RCON_PASSWORD`, the game logs, and required plugin health |
| A plugin loads defaults instead of operator settings | Confirm that the override exists under the exact `server/state/configs/<mode>/<target>` path |
| A changed `.env` value is ignored | Rerun setup so Docker Compose can recreate the affected container |
| The server appears twice in the LAN browser | Keep `CS2_TV_ENABLE=0`, rerun setup, and restart the active mode. When CSTV is enabled, the second entry is the CSTV endpoint on port `27020` |
| Two different game servers remain visible with CSTV disabled | Run `docker ps --format "table {{.Names}}\t{{.Ports}}"` and stop any older CS2 container or native server process that is still running |
| Panel login credentials are unknown | Read `PANEL_USERNAME` and `PANEL_PASSWORD` from the local `.env` file |

## Development verification

Run the Python unit and repository contract suite.

```bash
python3 -m unittest discover -s server/tests -v
```

Check Python and shell syntax.

```bash
python3 -m py_compile panel/*.py server/runtime/mode_manager.py
bash -n server/runtime/runtime-launcher.sh server/frameworks/install-linux.sh server/updater/updater.sh server/scripts/*.sh
```

Check the dashboard JavaScript embedded in the HTML page.

```bash
sed -n '/<script>/,/<\/script>/p' panel/templates/index.html | sed '1d;$d' | node --check
```

Validate Docker Compose after preparing a local `.env`.

```bash
docker compose config --quiet
```

Run the customized allocator tests after changing its source.

```bash
dotnet test plugins-src/retakes-allocator/cs2-retakes-allocator.sln --configuration Release
```

Run the live smoke test only after a complete installation.

```bash
PANEL_AUTH='admin:<password>' ./server/scripts/smoke-test.sh
```

The smoke test exercises the live panel, mode switching, managed file isolation, required payloads, and the rule that SteamCMD does not run in the game container.

## Related source repositories

- [MatchZy](https://github.com/shobhit-pathak/MatchZy)
- [CS2 Retakes](https://github.com/B3none/cs2-retakes)
- [HeroShift](https://github.com/arikitos/cs2-heroshift)
- [Warcraft Classic](https://github.com/arikitos/cs2-warcraft3)
- [RetakesAllocator upstream](https://github.com/yonilerner/cs2-retakes-allocator)
- [CounterStrikeSharp](https://github.com/roflmuffin/CounterStrikeSharp)
