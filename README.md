# CS2 Local

A local control panel for **one personal CS2 dedicated server**. Download this repository on your computer, bootstrap the panel with Docker Compose, then click **Install & start server** in your browser.

This first implementation includes a guided installer, administrator authentication, persistent game storage, health-checked startup, start/stop/restart, an update approval dialog, and a live console with authenticated RCON commands. Mode/plugin and Workshop management are later milestones; they are not implemented in this installer release.

## Requirements

- Docker Engine or Docker Desktop, running **Linux containers**, plus Docker Compose v2.
- An **x86-64 / amd64** machine. Windows with Docker Desktop/WSL2, Linux, and Intel macOS are the intended targets. ARM/Apple Silicon is explicitly rejected; CS2 is an x86-64 binary and emulation is not a supported guarantee.
- Internet access for Valve's Steam Runtime 4 SDK/Python images, Linux packages, SteamCMD and the first game download.
- At least **80 GiB free storage assigned to Docker**, with extra space for updates and Workshop maps. Prefer at least 8 GiB RAM assigned to Docker. The Steam Runtime SDK image and packages need additional space before the game-volume check can run.
- Available host ports `8080` (panel) and your selected game port (default `27015`).

There is no host Python/Node/SteamCMD dependency. A webpage cannot start Docker before its own service exists, so the Compose command below is the one-time bootstrap. Everything related to the game installation runs after clicking Install.

## Start the panel

From the downloaded repository directory:

```sh
docker compose up -d --build
docker compose logs panel
```

Open **http://localhost:8080**. Copy the **First-time setup token** from the panel logs, create a username and a password of at least 12 characters, then complete the installation form.

The setup token prevents another browser from claiming an unconfigured panel. It is needed once per new panel-state volume. Do not post it publicly. After setup, sign in with your administrator account; Steam authentication is not used for panel login.

## What the installer asks for

| Field | Purpose |
| --- | --- |
| Administrator username and password | Full control through the panel and its API. Password stored as a salted scrypt hash. |
| Server name | Name visible to players. |
| Network access | This computer only, local network, or internet. |
| Game port | UDP game traffic. TCP RCON is published only to host loopback. |
| Player slots and initial map | Initial competitive server configuration. |
| Join password (optional) | Private access for players, separate from the panel password. |
| GSLT (internet mode only) | Steam Game Server Login Token, created for app ID **730** at https://steamcommunity.com/dev/managegameservers. |

**No Steam username, password, Steam Guard code, or SteamID is needed to download CS2.** SteamCMD uses anonymous login. SteamID alone does not prove identity or grant administrator privileges; game-side SteamID permissions will be added when an admin plugin is integrated. The panel administrator can already send server commands through authenticated RCON. RCON gets a separate, randomly generated password automatically.

The installation builds a Linux SteamCMD runtime using Valve's Steam Runtime 4 SDK, creates/reuses a persistent game volume, checks available space, runs `app_update 730`, writes your server config, starts CS2 through its official `cs2.sh` launcher, and waits for a successful A2S_INFO query before showing **Ready**. An internal socat proxy allows authenticated RCON access even when CS2 binds its RCON listener to container loopback. Installation activity appears in the dashboard. A failed/interrupted download can be retried without deleting the game volume; SteamCMD resumes/checks the existing installation.

## Connect and networking

For this computer, open the CS2 console and run:

```text
connect 127.0.0.1:27015
```

Use the selected port if different. For LAN, other players use your computer's LAN IP. For internet, manually permit the game UDP port in your firewall and forward it on your router. Docker cannot automatically configure your router, guarantee connectivity behind CGNAT, or keep a sleeping/offline computer running. The panel remains accessible **only on localhost** in every network mode.

## Persistence and updates

- `cs2-local-game`: the full game installation, Steam manifest and future Workshop cache. Created by the installer.
- `cs2-local-config`: generated server settings, GSLT, join password and RCON password.
- `cs2-local-panel-state`: administrator hash, bootstrap token before setup, and operation state. Sessions expire after eight hours and are invalidated on panel restart.
- `cs2-local-server`: game container, created by the installer, with `unless-stopped` restart policy. It runs independently of the panel.
- `cs2-local-job`: temporary installer/check/update container. No automatic game update occurs in the server entrypoint.

**Start** on a stopped server reads the installed manifest and asks SteamCMD for the public branch BuildID. This downloads metadata, not the game. If a newer build is found, the panel shows **Update & start / Cancel**. Approval is tied to that specific build and checked again before updating; a changed public build requires fresh approval. If Steam metadata cannot be checked, startup fails visibly and can be retried. Restart stops the server, then follows the same update gate. A crash/host reboot recovery via Docker's restart policy uses the already installed game without an update prompt.

`docker compose down` stops the panel but **does not stop the separately managed game container**. Stop the game in the panel first if you want both stopped. Do not use `down -v` unless you intend to remove panel credentials and settings. Do not delete the game volume to upgrade the panel.

## Authentication and API

The browser authenticates with an HttpOnly, SameSite=Strict session cookie. State-changing requests additionally require the session CSRF token. Requests with non-loopback Host headers or a different Origin are rejected. Credentials and game tokens are not returned by status/console APIs; known tokens are redacted from displayed logs. Configuration files are plaintext private Docker-volume files, not an encrypted secrets vault; users with Docker/host access can inspect them.

The panel mounts the Docker socket to build and manage its runtime. **Docker socket access grants powerful host control.** This panel is intended for a trusted, local owner and must not be exposed as a public hosting control panel. The complete API is available to the authenticated owner:

| Endpoint | Function |
| --- | --- |
| `GET /api/session` | Setup/login state and CSRF token for an existing session. |
| `POST /api/setup` | One-time admin creation with `setup_token`, `username`, `password`. |
| `POST /api/login` | Create an eight-hour session. Login attempts are rate limited. |
| `GET /api/preflight` | Docker OS/architecture and assigned RAM. |
| `GET /api/status` | Sanitized installation state, server health and installation logs. |
| `POST /api/install` | Validate settings and queue installation. Returns 202. |
| `POST /api/start` | Check updates before starting; optionally supply `approved_build`. |
| `POST /api/stop`, `POST /api/restart` | Server lifecycle operations. |
| `GET /api/console` | Recent game logs, with known secrets redacted. |
| `POST /api/command` | Send `{"command":"status"}` through RCON. |
| `POST /api/logout` | Invalidate session. |

POST requests use `Content-Type: application/json`; authenticated POST requests use `X-CSRF-Token`. The UI handles cookies/tokens automatically. SteamCMD installs/updates software; RCON sends commands to the running game server.

## Development and verification

The panel uses Python's standard library only. Run the offline tests:

```sh
python3 -m unittest discover -s tests -v
node --check panel/static/app.js
sh -n runtime/entrypoint.sh
```

Tests cover setup/authentication/CSRF, public BuildID parsing, install persistence/readiness, update approval and no-download startup, retry failures, operation locking, redaction and multipart RCON responses. Docker is mocked in those tests. The build/download/readiness path still requires a real Docker/Steam smoke test; it has not been executed in the development environment where this initial implementation was authored.

On a real Docker host, verify: bootstrap the panel, complete Install, connect in CS2, send `status` from Console, stop/start with the same game volume, restart the panel and log in again, and confirm failed download/update-check errors can be retried. A naturally available Steam update is needed to validate the update dialog against Valve's live data. Windows/Linux/Intel macOS integration has not yet been independently verified.

Sources: [Valve dedicated server documentation](https://developer.valvesoftware.com/wiki/Counter-Strike_2/Dedicated_Servers), [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD), [Docker Engine API](https://docs.docker.com/reference/api/engine/), [Docker platform compatibility](https://docs.docker.com/build/building/multi-platform/).
