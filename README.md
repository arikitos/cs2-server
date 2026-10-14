# CS2 Control

A Docker-based control panel for **one CS2 server**, with **FaceIt competitive** and **Retakes** presets. The dark dashboard includes live resource usage, game controls, an RCON command library, player management, mode configuration, lobby passwords, maintenance jobs, configuration backups and an activity log.

## Requirements

- Docker Engine with Compose v2 or newer, or Docker Desktop using Linux containers.
- An x86-64 / amd64 machine. CS2 is an x86-64 Linux binary; ARM hosts, including Apple Silicon, are not supported by these setup scripts.
- Enough disk space for the Steam CS2 installation and its updates. No host Python, .NET SDK, Node.js or SteamCMD is needed.
- For an internet-listed server, a Steam Game Server Login Token (app ID `730`): [Steam token management](https://steamcommunity.com/dev/managegameservers).

## Quick start

```bash
git clone https://github.com/arikitos/cs2-server.git
cd cs2-server
```

On Linux or Intel macOS:

```bash
bash server/scripts/setup.sh
```

On Windows, run `server\scripts\run-setup.cmd`, or use PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File server/scripts/setup.ps1
```

Setup generates `.env` with random panel and RCON passwords if the file is absent, prepares storage, builds the Docker images, installs or reuses the Steam game files, installs the pinned frameworks and starts the panel. The first Steam download can take a while. The game is left stopped until you choose a mode.

1. Open [http://127.0.0.1:8080](http://127.0.0.1:8080).
2. Log in using `PANEL_USERNAME` and `PANEL_PASSWORD` from `.env`.
3. Open **Game modes**, choose **FaceIt** or **Retakes**, set the name and map pool, then press **Save & start**.
4. Wait for **Online**, then use the connection command shown on the dashboard.

To set the Steam token before installation, copy `.env.example` to `.env` and fill `SRCDS_TOKEN`, `PANEL_PASSWORD` and `CS2_RCON_PASSWORD`. Compose refuses to start with missing management passwords. The Windows setup script can fill blank passwords; the Bash script preserves an existing `.env` unchanged.

## Network configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CS2_PORT` | `27015` | Published game TCP/UDP port |
| `CS2_PUBLIC_ADDRESS` | Panel host | IP or DNS name displayed in the connection command |
| `PANEL_BIND` | `127.0.0.1` | Host interface accepting panel connections |
| `PANEL_PORT` | `8080` | Panel HTTP port |
| `CS2_DATA_PATH` | `./server/cs2` | Persistent Steam installation on the host |
| `PROJECT_PATH` | `.` | Repository root on the host |
| `CS2_TV_ENABLE` | `0` | Enable CSTV in the game configuration |

For a home server, forward the configured game port on your router and allow it through your firewall. Set `CS2_PUBLIC_ADDRESS` to the address players use. For panel access from your LAN, set `PANEL_BIND` to the host's LAN IP. Recreate containers after changing `.env`:

```bash
docker compose create cs2-game
docker compose up -d --no-deps panel
```

The panel has owner-level access to Docker through its socket. Keep the panel on localhost or a trusted LAN. For remote management, use an SSH tunnel, or an HTTPS reverse proxy with access controls. The panel uses HTTP Basic authentication, blocks cross-origin mutations, requires JSON and `X-CS2-Panel: 1` for writes, redacts secrets in logs, and sends a restrictive Content Security Policy.

CSTV ports are not published by default. If you enable CSTV, add TCP/UDP mappings for `CS2_TV_PORT` to `cs2-game` in `compose.yml`.

## Modes

| Preset | Implementation | Configuration |
| --- | --- | --- |
| FaceIt | MatchZy 0.9.1 | Fixed 5v5, ten ready players, knife round, competitive rules, pauses and overtime |
| Retakes | B3none Retakes 3.1.1 | 4v3 or 5v4, automatic plant, Instadefuse and the existing customized automatic loadout progression |

**FaceIt** is the name of the local competitive preset. It does not integrate with the FACEIT platform or its anti-cheat service. MatchZy retains ownership of match rules. Use the console's plugin commands for match operations; the panel manages the name, start map and map pool.

Retakes retains the customized allocator's five-stage round progression and 25% AWP chance in its final stage. Its source and license are under `modes/retakes/source/allocator`. Each preset has its own saved settings. Saving does not disrupt a match; settings apply on the next start or restart. Switching presets restarts the same game container.

The pinned frameworks are **Metamod 2.0.0-git1476** and **CounterStrikeSharp 1.0.376 with .NET 10 runtime**. Exact release URLs and SHA-256 hashes are recorded in `server/frameworks/versions.json`; the installer verifies both downloads before installing them. MatchZy and Retakes release payloads are bundled in the repository.

## Architecture and storage

| Directory | Contents |
| --- | --- |
| `panel/` | Flask API, Gunicorn entry point, templates and browser assets |
| `modes/faceit/` | Competitive plugin payload, configuration and manifest |
| `modes/retakes/` | Retakes payload, configuration, manifest and allocator source |
| `server/runtime/` | Game image, launcher and transactional mode deployment |
| `server/updater/` | SteamCMD maintenance image; never starts the game |
| `server/frameworks/` | Pinned framework installer and managed CSS configuration |
| `server/scripts/` | Cross-platform setup and lifecycle commands |
| `server/config/` | Shared server configuration template |
| `server/state/` | Local settings, secrets, inventory, audit files and backups; ignored by Git |
| `server/cs2/` | Default persistent Steam installation; ignored by Git |

One Steam installation, one game process, one active preset. The runtime deploys only the chosen preset and removes only files recorded in its previous managed-file inventory. Mode changes are transactional; unmanaged installation files are preserved. SteamCMD runs separately after the game is stopped. Keep the entire `server/state` directory when upgrading: it contains the inventory needed to safely remove old mode files.

Existing `matchzy` panel settings are migrated to `faceit` with a 5v5 format. The removed presets are no longer offered. Their previously deployed files are removed through the existing managed inventory on the next start.

In-game administrator lists start empty on new installations. To grant yourself CSS admin rights, add your Steam ID and flags to `server/frameworks/counterstrikesharp/configs/admins.json` and run the framework installer. It merges the configured entries with the existing admin list. Existing MatchZy administrator entries are preserved under `server/state/configs/faceit/cfg/MatchZy/admins.json` when upgrading; that saved file can be edited for match-specific administrators.

## Operations

```bash
# Start the panel and create a stopped game container
bash server/scripts/start.sh

# Stop the game and panel
docker compose stop cs2-game panel

# Watch game or panel output
docker compose logs --tail 100 -f cs2-game
docker compose logs --tail 100 -f panel

# Rebuild the panel after pulling code
docker compose up -d --build --no-deps panel
```

Use **Maintenance** in the panel to update or validate Steam files, repair Metamod, verify the installation, create backups and restore configuration. Jobs stop the game and block concurrent writes. A previously running mode resumes after successful maintenance; an already stopped server stays stopped. Failed maintenance leaves the game stopped for recovery.

To install the pinned framework versions after pulling an update:

```bash
docker compose stop cs2-game
docker compose --profile maintenance run --rm cs2-modinstaller
docker compose --profile maintenance run --rm \
  -e CS2_UPDATER_MODE=repair-metamod -e 'CS2_UPDATER_CONFIRM=UPDATE CS2' cs2-updater
```

Then start a mode from the panel. For a full installation refresh, re-run the setup script.

Configuration backups include panel settings, saved plugin configuration and runtime state. They exclude the Steam installation, demos and live plugin databases. Restore creates a safety backup and leaves the game stopped. Copy the game data separately if you need a full host backup.

The repository keeps build and syntax validation workflows, without test directories. The allocator workflow builds its deployable payload and updates `main` when its source changes. Container images use the existing pinned CS2 base; package updates are explicit, reproducible changes to the version manifest.
