# CS2 Local

A Docker control panel for **one personal internet CS2 server**. Bootstrap the panel, create your panel administrator, then click **Install & start server**. The game always uses **27015/UDP**; the panel remains on **localhost:8080**.

This version combines the new installer/authentication/layout with the legacy server's transactional mode deployment and customized automatic Retakes loadouts.

## Start

Requirements: Docker Engine or Docker Desktop with Compose v2, **Linux amd64 containers**, internet access, at least **80 GiB free in Docker** for the game plus additional runtime/update space, and preferably at least 8 GiB assigned RAM. Intended hosts: Linux x86-64, Windows with Docker Desktop/WSL2, and Intel macOS. ARM/Apple Silicon is rejected. No host Python, Node, .NET or SteamCMD is required.

```sh
docker compose up -d --build
docker compose logs panel
```

Open **http://localhost:8080**. First-time setup collects the required data in two steps:

1. **Panel account**: copy the one-time **setup token** from the logs, choose your first administrator **username** (3-32 letters, numbers, dots, dashes or underscores), and a **panel password** (12-128 characters).
2. **Server and Steam**: enter Server Name, Player Slots, Map, Join Password and game mode, then supply a **Game Server Login Token (GSLT)** for app ID **730**, created at [Steam game server accounts](https://steamcommunity.com/dev/managegameservers). Public IP and port are detected/fixed automatically. A blank Join Password opens the server.

SteamCMD downloads CS2 anonymously. Do not supply a Steam password, Steam Guard code or SteamID for the download. The panel account and in-game admin permissions are separate. RCON receives an independent random password automatically.

A browser cannot bootstrap Docker before the panel exists, so the Compose command is the only initial host step. Install prepares the runtime and plugins, checks the persistent game directory, verifies/downloads CS2, starts the selected mode, and waits for A2S readiness plus RCON verification of the required frameworks and plugins. Failed downloads can be retried without deleting the game volume. The panel account must be created and authenticated before installation can start; installation refuses missing/invalid Steam tokens before doing any game work.

## Existing files and repeat installation

The server installation is the **`/game` directory inside the persistent Docker volume `cs2-local-game`**. It is not a disposable container directory or a host Steam client install. The installer creates this managed volume when missing and reuses it on every run:

- **No game directory/files**: create the installation directory and download CS2 with anonymous SteamCMD.
- **Existing or partial installation**: retain the directory and run **`app_update 730 validate`** in place. SteamCMD checks the official file contents, repairs missing/changed files, resumes downloads and updates the public build. A manifest/BuildID alone does not count as verified files.
- **Before starting**: require SteamCMD's explicit success, the manifest, executable launcher/binary and game metadata, then fetch the current public BuildID and require a match. Verification/network errors or a newer build appearing during validation leave the server stopped and show a retryable error.

After installation, **Maintenance → Verify & update server** runs this same installer again with the saved configuration. It backs up settings/user policy, stops a running game before touching game files, verifies/updates in place and starts after success. It preserves your panel username/password, GSLT, RCON password, server settings and user registry. A previously interrupted installer can resume; an old runtime's unfinished download receives full validation by the new runtime before startup.

Install and **Verify & update server** explicitly authorize downloading required updates; ordinary **Start/Restart** keep their existing update-approval popup. Validation can restore modified official Steam files. Managed server/mode settings and the Metamod search path are reapplied on launch; manually changed official game files should be backed up separately. No Steam account password or Steam Guard code is requested or stored.

## Dashboard

The dashboard contains, in order:

1. **Your CS2 Server**, status and Start/Restart/Stop.
2. **Players**, with Kick, permanent Ban and game Admin actions.
3. **Server settings**: Server Name, read-only public IP + Port, Player Slots, Map and Join Password. **An empty Join Password makes the server open.**
4. **Game mode**, above which the permanent **Metamod + CounterStrikeSharp** base is shown.
5. Health, CPU/memory usage, installed build, mode commands and installation activity.

The public IPv4 address is detected by the panel through HTTPS IP lookup services, displayed as `IP:27015`, and copied using **Copy**. Failed lookup shows an explicit unavailable state rather than substituting a LAN address. Refresh after an ISP/VPN address change. This is address discovery, not an inbound connectivity test: allow and forward **27015/UDP** on your firewall/router. CGNAT and VPN routing can prevent external access despite a detected public IP. The game is always Internet mode (`sv_lan 0`). TCP RCON is published only to `127.0.0.1:27015` through an internal proxy; never expose the panel or RCON to the internet.

## Modes and plugins

| Selection | Gameplay | Active mode plugins |
| --- | --- | --- |
| FaceIt (MatchZy) | Competitive match flow, ready-up, practice and official MatchZy commands | MatchZy |
| Retakes (B3none) | Retake rounds, autoplant, Instadefuse and the legacy customized automatic loadout sequence | RetakesPlugin, RetakesAllocator, InstadefusePlugin |
| Deathmatch (Official) | Valve's standard deathmatch (`game_type 1`, `game_mode 2`) | No MatchZy/Retakes plugins |

**FaceIt is a preset label, not integration with the FACEIT platform or its anticheat.** Player Slots sets server capacity. Retakes caps active participants at 10; the remaining capacity is available for its queue/spectators. MatchZy owns its match rules.

Metamod, CounterStrikeSharp **with its .NET runtime**, and the source-built **LocalManager** plugin stay installed in every mode. The custom allocator is rebuilt from its preserved legacy source. Upstream component versions are pinned in [runtime/components.json](runtime/components.json), with release SHA-256 verification where published. Metamod and Instadefuse have fixed release URLs but no upstream digest in this catalog; their observed hashes are recorded in the built image. Versions are checked at deployment and the Metamod `gameinfo.gi` search path is repaired after Steam updates. Framework installation and plugin downloads happen during image build; the game entrypoint never runs SteamCMD.

Saving settings while running stops and restarts the game using the current installed build. The legacy file inventory manager replaces only managed mode files and retains the permanent framework and unrelated files. Failed deployment rolls back its files; failed configuration/startup restores the previous settings and attempts to restart the previous mode. Saving while stopped leaves the game stopped.

This release deliberately offers the three requested modes. Workshop/Community Maps management is not yet implemented. Existing unmanaged plugin files are not silently deleted to resolve an import conflict.

## Players, bans and administrators

**Users & bans** contains everyone recorded by the server's Steam authorization callback, indexed by SteamID64. The game plugin records first/last seen times, current name and visit count even while the web panel is stopped. Bots and players awaiting Steam authorization cannot receive persistent user actions.

- **Kick** resolves the authenticated SteamID in the running server; it never applies an old/reused numeric player slot to another player.
- **Ban** is permanent until **Unban**, survives restarts and is enforced again on authorization and by the permanent management plugin.
- **Admin** assigns `@css/root` through CounterStrikeSharp's managed `admins.json`. Removing it reloads game permissions. It does not grant web panel access. A banned user's admin privileges are suspended while the ban is active.

The authoritative panel registry is `/state/users.json`. The panel generates private `/control/admins.json` and `/control/policy.json`; the game mounts this policy volume read-only. The plugin writes `/telemetry/users-seen.json` and the timestamped `/telemetry/live.json` snapshot. Stale snapshots are shown as unavailable rather than falsely listing players as online. If RCON is unavailable when a ban/admin change is saved, the UI reports pending synchronization; the game plugin also polls the persistent policy independently.

## Persistence, updates and maintenance

| Docker volume | Contents |
| --- | --- |
| `cs2-local-game` | CS2 installation, Steam manifest, mode inventory and generated game config |
| `cs2-local-config` | Server settings, GSLT, game password and RCON password |
| `cs2-local-panel-state` | Panel account hash, operation state, users, audit log and private configuration backups |
| `cs2-local-control` | Generated game admin permissions and ban policy |
| `cs2-local-telemetry` | Persistent game-side player history and live snapshot |

On **Start** of a stopped server, SteamCMD retrieves public branch BuildID metadata. If the build differs, **Update & start / Cancel** asks for approval tied to that exact build and checks again before downloading. Same-build startup does not download the game. **Restart** follows this gate after stopping. Docker crash/reboot recovery uses the installed game without an update prompt. Copying the repository to another computer does not transfer these volumes; a new computer installs its own game unless the volumes are migrated.

**Maintenance** offers configuration/user-policy backups and restore, forced reinstallation of the pinned framework/plugins, and SteamCMD **Validate**. Maintenance stops a running game first; normal successful completion restarts it. Validation explicitly downloads missing/changed game files and is separate from ordinary startup. Backup/restore covers generated server settings, credentials, users, bans and admin permissions, **not** the full game install or arbitrary manually edited plugin files.

The game container is independently managed as `cs2-local-server`; `docker compose down` stops the panel only. Stop the game in the panel first to stop both. Do not remove volumes to update the panel. `docker compose down -v` deletes panel credentials/settings/policy/history and is not an upgrade command.

## Upgrading or importing an old installation

For an earlier CS2 Local installation, rebuild the panel with `docker compose up -d --build` while keeping its volumes. Open settings, supply a GSLT if the previous server was local/LAN, select a mode and save. The next launch creates the new plugin runtime around the retained game files. Previous Docker runtime images are not automatically deleted.

The Windows ZIP version used bind-mounted game directories and a different state/authentication format. Its repository has no live game installation or user state to import. Its Retakes customization and mode deployment engine are included in this release. For an existing deployed Windows server, keep the original game folder/state untouched, stop its game, and migrate a copy into the new named volume rather than running two servers against one writable installation. Its old Basic Auth password is not automatically imported as the new panel administrator. Existing volumes/folders without this panel's ownership label are refused. Keep custom plugin configurations and game-side admin/history backups for an explicit migration; the installer must not guess host paths or silently overwrite unmanaged files.

## Authentication and API

The first claim requires the one-time setup token. Panel passwords are stored as salted `scrypt` hashes. Authentication uses an eight-hour **HttpOnly, SameSite=Strict** cookie; sessions expire on panel restart. All authenticated POST operations also require **X-CSRF-Token**. Non-loopback Host headers and foreign Origins are rejected. Login attempts are rate limited.

Steam/RCON credentials never appear in status, user, backup-list or console responses; known secrets and credential-setting commands are redacted from logs. The authenticated **settings** endpoint intentionally lets the owner read/edit the **game join password**. Configuration and backups are private plaintext Docker files, not encrypted storage; host/Docker administrators can read them. The panel mounts the Docker socket and is intended only for the trusted local owner.

| Endpoint | Operation |
| --- | --- |
| `GET /api/session`, `POST /api/setup`, `/api/login`, `/api/logout` | Panel account/session |
| `GET /api/preflight`, `/api/status`, `/api/metrics` | Docker support, lifecycle and usage |
| `GET /api/settings`, `POST /api/configure` | Owner settings; saving may restart the game |
| `GET /api/address`, `POST /api/address/refresh` | Public IPv4 + fixed port |
| `POST /api/install`, `/api/start`, `/api/stop`, `/api/restart` | Install/repeat verification/lifecycle; install accepts saved settings, start may take `approved_build` |
| `GET /api/players`, `/api/users` | Live players and persistent user registry |
| `POST /api/users/action` | `{steamid, action}`: kick, ban, unban, admin, remove_admin |
| `GET /api/modes`, `POST /api/mode/action` | Mode catalog and registered mode commands |
| `GET /api/console`, `POST /api/command` | Redacted game logs and owner RCON commands |
| `POST /api/backup`, `GET /api/backups`, `POST /api/restore` | Configuration/user backup; restore takes `id` |
| `POST /api/repair`, `/api/validate`, `GET /api/audit` | Controlled maintenance and action history |

POST bodies are JSON. The browser manages its cookie and CSRF header. SteamCMD installs/updates files; RCON operates the running game.

## Verification

```sh
python3 -m unittest discover -s tests -v
node --check panel/static/app.js
sh -n runtime/entrypoint.sh
docker compose config --quiet
```

Python tests cover authentication/API boundaries, first account/token requirements, empty/partial/complete/damaged installation detection, verified reuse and update failures, BuildID approvals, download persistence, operation locks, durable bans/admins/history, owner settings, public IP validation, backups, configuration rollback, safe archive extraction and transactional mode isolation. Docker and SteamCMD execution are mocked in these local tests.

CI additionally compiles the .NET plugins, tests the legacy allocator, builds the real Docker runtime through the production Engine API, checks actual pinned archives and deployment of all three mode payloads, verifies runtime user access to private config/policy, and exercises the desktop/mobile panel using a deterministic browser fixture. Browser screenshots are attached to the CI run; fixture players/IP/usage are explicitly simulated test data.

A full **CS2 download, real game launch, joining from CS2 and internet connectivity test** still requires a Docker host with sufficient disk space and a valid owner's GSLT. Real ban/reconnect and admin command behavior must be verified there. Windows/Linux/Intel macOS game integration is not independently certified by the offline or synthetic-deployment tests.

Upstream references: [CounterStrikeSharp installation](https://github.com/roflmuffin/CounterStrikeSharp/blob/main/INSTALL.md), [admin framework](https://docs.cssharp.dev/docs/admin-framework/defining-admins.html), [Metamod releases](https://mms.alliedmods.net/mmsdrop/2.0/), [MatchZy](https://shobhit-pathak.github.io/MatchZy/installation/), [B3none Retakes](https://github.com/B3none/cs2-retakes), [legacy allocator source](runtime/plugins/retakes-allocator/ARIKITOS_CUSTOMIZATION.md).
