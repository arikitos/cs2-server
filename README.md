# CS2 Manager

A Docker Compose stack that runs a Counter-Strike 2 dedicated server in one of
four game modes, controlled entirely from a local web panel — start/stop/restart,
switch modes, edit the server config, manage the password, run RCON, view
players, and read separated logs. The panel is the single control plane; it never
exposes a host shell or arbitrary Docker access to the browser.

**Architecture principle:** normal operation (start / stop / restart / switch mode)
and game updates are strictly separated. Every game service runs from a pinned,
custom runtime image whose entrypoint (`manager/runtime/runtime-launcher.sh`)
**never invokes SteamCMD** — a boot can no longer clobber `gameinfo.gi` or the
Metamod search path. SteamCMD only ever runs inside the dedicated `cs2-updater`
service, which is off by default, requires an explicit confirmation phrase, and
is triggered as its own maintenance action from the panel.

## Project Structure

The repo root holds Compose orchestration; everything the stack manages lives
under `manager/`. `server/` is the host's CS2 dedicated-server install
(`CS2_DATA_PATH`) — gitignored, not part of the repo's managed content.

| Path | Responsible for |
|---|---|
| `compose.yml` | Defines the four game services (`cs2-faceit`, `cs2-retakes`, `cs2-superheroes`, `cs2-gungame`), the maintenance-only `cs2-updater` and the `panel`, all under Compose project `cs2-server`. |
| `.env.example` / `.env` | Host paths, secrets (GSLT, RCON password, panel credentials), and per-mode capacities. |
| `start-windows.ps1` / `stop-windows.ps1` | Quick Windows entry points: create the game containers (stopped) and start/stop the panel. |
| `manager/runtime/` | The custom, no-SteamCMD runtime image (`Dockerfile` + `runtime-launcher.sh`) every game service builds from. |
| `manager/updater/` | The isolated SteamCMD image (`Dockerfile` + `updater.sh`) — the only place that touches Steam. |
| `manager/panel/` | The Flask control-plane app (`app.py`, `mode_defs.py`, templates, static assets, its own `Dockerfile`). Talks to Docker over the mounted socket, generates per-mode configs, and speaks RCON to the running game container. `mode_defs.py` loads and validates the `mode.json` manifests, so the panel hard-codes no mode, plugin or action list. |
| `manager/shared/plugins/PanelBridge` + `manager/shared/plugins-src/PanelBridge` | The compiled `PanelBridge` plugin and its C# source. One copy, bind-mounted into **every** mode and declared as a util in every `mode.json` (`"shared": true`, with `build.project` pointing at the source). It exposes connected players with their SteamID64 over RCON (`css_panel_players`) — data the stock `status` command lacks — which is how the panel builds its player list and kick/ban actions. |
| `manager/modes/<mode-id>/` | One self-contained folder per mode: `mode.json` (the definition the panel reads), `cfg/` (`mode_<id>.cfg` + panel-generated `panel_runtime.cfg`), `config/` (plugin config the panel edits), `plugins/<Main>/` (the plugin that defines the mode) and `utils/<Helper>/` (every supporting plugin or shared library of that mode — Instadefuse, AutoReady, RetakesPluginShared, GunGameAPI, RayTrace). Modes stay isolated — no mode mounts another mode's plugins. |
| `manager/data/` | Panel state: `server.json` (active mode), `modes/*.json` (per-mode settings), `secrets.json` (gitignored), `audit/` (gitignored action log). |
| `manager/scripts/` | `migrate.ps1` (backup + build + first run), `rollback.ps1` (restore a config backup), `start.sh` / `stop.sh` (Linux/macOS equivalents of the Windows scripts), `smoke-test.sh` (panel API smoke test), `install-mods-linux.sh` (fetches Metamod/CounterStrikeSharp for a fresh host install; run via the `cs2-modinstaller` maintenance service). |
| `manager/backups/` | Timestamped pre-change backups written by `migrate.ps1` — config only, never the 60+ GB game install. |

## Modes

Every mode is defined by its own `manager/modes/<mode-id>/mode.json`; the table
below is a summary of those files, which are the source of truth.

| UI name | Mode id / folder | Main plugin + utils | Service | Capacity |
|---|---|---|---|---|
| FaceIt | `faceit` | MatchZy + AutoReady | `cs2-faceit` | 2–10 |
| Retake | `retake` | Retakes + Instadefuse, RetakesPluginShared | `cs2-retakes` | 3–10 |
| HeroShift | `superheroes` | HeroShift + RayTrace (random skill each round) | `cs2-superheroes` | 2–10 |
| GunGame | `gungame` | GG2 weapon ladder + GunGameAPI | `cs2-gungame` | 2–10 |

`PanelBridge` is a util of every mode (one shared copy, see the table above).

Retake runs RetakesPlugin + Instadefuse, with RetakesPlugin doing its own weapon
allocation (`EnableFallbackAllocation` true) — no allocator plugin is installed, and
the earlier "Retakes V2 alongside Retake" split is gone. See
[manager/modes/retake/README.md](manager/modes/retake/README.md).

Only one game service runs at a time; the panel enforces the port-27015 handoff.
HeroShift's skill roster **is** editable from the panel — per skill you can toggle
`Active`, set `Rarity` and cap `MaxPerServer`; skill mechanics ship with the plugin
build. See [manager/modes/superheroes/README.md](manager/modes/superheroes/README.md)
for the full roster/balance notes.

GunGame is the only mode that runs Casual (`game_type 0` / `game_mode 0`, as GG2
requires). Its ladder settings are files, not panel fields: edit
`manager/modes/gungame/cfg/gungame/*.json` on the host and reload live with the
`gg_config gungame` mode command. See
[manager/modes/gungame/README.md](manager/modes/gungame/README.md) for the
weapon order, the two documented deviations from the stock release, and why
`!rank` / `!top` are off.

### Mode definitions (`mode.json`)

A mode owns everything it needs in one folder, and declares it in one manifest:

```text
manager/modes/<mode-id>/
├── mode.json            the definition: container, startup cfgs, capacity range,
│                        settings defaults, plugin/util mounts, RCON quick actions
├── cfg/                 mode_<id>.cfg (base ruleset) + panel_runtime.cfg (generated)
├── config/              plugin config files the panel edits
├── plugins/<Main>/      the plugin that defines the mode
├── utils/<Helper>/      every supporting plugin or shared library of that mode
└── utils/<Helper>.src/  C# source of a helper built in-house (FaceIt's AutoReady),
                         declared as that plugin's `build.project`
```

An in-house helper's source sits *next to* the folder that is bind-mounted as the
live plugin, never inside it, so `bin/`/`obj/` build output never lands in the
server's plugin directory. `PanelBridge` is the exception every mode shares: one
build and one source tree in `manager/shared/`, declared with `"shared": true`.

The panel reads these manifests at boot (`manager/panel/mode_defs.py`) and derives
the mode list and order, each mode's labels, container, capacity range, config
defaults, extra convars, required-plugin health checks and whitelisted RCON quick
actions from them. There is no mode, plugin or action list in the panel code.

Every mount is validated: sources must be relative paths inside the mode folder
(or `manager/shared/` when marked `"shared": true`, which is how each mode declares
the single `PanelBridge` copy), targets must sit under `addons/` or `cfg/` relative
to `game/csgo`, and generated cfg lines / action commands must be plain
`convar value` text — no quotes, semicolons or newlines can reach a cfg or RCON.

**To add a plugin to a mode:** drop it in that mode's `plugins/` (a main plugin) or
`utils/` (a helper or shared library), add an entry to `mode.json` with its mount
source and target, add the matching bind mount to that mode's service in
`compose.yml`, then recreate the container and restart the panel. Maintenance →
**Verify mounts** lists every declared source and whether it exists, and an invalid
`mode.json` is reported there and refused by Panel Rebuild instead of loading
half a mode.

## How it works end to end

1. **Provision.** `migrate.ps1` (or `start.sh`) copies `.env.example` → `.env` if
   missing, backs up existing config to `manager/backups/`, builds the runtime,
   updater and panel images, `docker compose create`s the four game services
   (stopped, no SteamCMD involved), and starts the panel.
2. **Panel boots.** The Flask app (`manager/panel/app.py`) authenticates every
   request with Basic Auth, mounts the host Docker socket, and mounts
   `manager/data`, `manager/modes`, the whole project (rw, for backups/rebuild)
   and the CS2 install (ro, for inspection).
3. **Start / switch a mode.** The panel stops any other running game service to
   free port 27015, writes a fresh `panel_runtime.cfg` for the target mode from
   `manager/data/modes/<mode>.json`, then starts that mode's container via the
   Docker API.
4. **Container boot (no SteamCMD).** `runtime-launcher.sh` runs read-only health
   checks (game files present, Metamod search path intact — repair is a separate
   maintenance action, never automatic), templates `server.cfg`, and execs
   `cs2.sh` with `+exec mode_<mode>.cfg +exec panel_runtime.cfg`, which load the
   mode's base ruleset and the panel's current settings in that order.
5. **Live control.** The panel talks to the running container over Source RCON:
   `PanelBridge` (mounted in every mode) answers `css_panel_players` with
   SteamID64-tagged player data for the Players view; the RCON Console sends
   admin/whitelisted commands (risk-classified server-side); "Apply live" pushes
   hot convars (`max rounds`, `freeze time`, `friendly fire`, `bots`) without a
   map reload, while `capacity`/`map` changes apply on the next start/restart.
6. **Update CS2 (maintenance only).** The Owner triggers the `cs2-updater`
   service with a confirmation phrase. It runs SteamCMD `app_update`, repairs the
   Metamod search path, verifies the install, and exits — the panel then restarts
   whichever mode was active. Runtime containers never take this path.
7. **Rollback.** `rollback.ps1` restores a `manager/backups/pre-v3-*` snapshot
   (config only); the persistent game install and plugin mounts are untouched.

## Setup

1. Copy `.env.example` to `.env` and edit values (`SRCDS_TOKEN`, `CS2_RCON_PASSWORD`,
   `PANEL_USERNAME`/`PANEL_PASSWORD`, `CS2_DATA_PATH`). The pinned `CS2_BASE_IMAGE`
   and per-mode capacities have sane defaults.
2. Migrate / first run (Windows): `./manager/scripts/migrate.ps1` (or `./start-windows.ps1`).
   Linux/macOS: `manager/scripts/start.sh`.
3. Open the panel at `http://127.0.0.1:8080`.

## Prerequisites

- Docker Desktop with the Compose plugin (WSL 2 backend on Windows).
- A CS2 dedicated-server install on the host (`game/`, `bin/`, …) at
  `CS2_DATA_PATH`. Not included in this repo. Install/update it via the maintenance
  updater, not on normal boot — see
  [Bootstrapping an empty `CS2_DATA_PATH`](#bootstrapping-an-empty-cs2_data_path)
  if the directory is empty.
- A Steam Game Server Login Token (GSLT) for a public server.

## Operating

The panel is organised into five sections:

1. **Status** — operational state, active mode, endpoint, per-container run state,
   plugin health, and the top-level Start / Stop / Restart / Refresh controls.
2. **Game Mode** — the four modes with the active one marked; select one to edit
   and start / switch to it.
3. **Server Config** — a unified set of fields for the selected mode:
   `map`, `capacity`, `max rounds`, `freeze time`, `friendly fire`, `bots`, plus the
   server `password`. Defaults match each mode's official cfg (HeroShift =
   Competitive), with friendly fire **off** by default and the password disabled.
   On FaceIt, MatchZy governs max rounds / freeze time / friendly fire during a live
   match, so those apply to warmup / non-match play.
4. **RCON Console** — players (left), console (center), and the active mode's
   whitelisted commands (right); clicking a command drops it into the input to send.
   Live, redacted, source-separated logs sit below.
5. **Maintenance** (owner) — verify mounts, backup, repair Metamod, update / validate
   CS2, restart / rebuild panel, each labelled with when to run it.

- **Start / Stop / Restart** a mode and **switch** modes — none run SteamCMD.
- **Apply live** hot-applies `max rounds` / `freeze time` / `friendly fire` / `bots`
  over RCON with no map reload; `capacity` and `map` take effect on the next start /
  restart. Old on-disk settings collapse to the unified fields automatically.
- **Password** is enabled/disabled/changed from Server Config and is never returned by
  the API or written to logs/audit.

## Updating CS2 (maintenance only)

SteamCMD runs **only** in `cs2-updater`, which is stopped by default and requires a
confirmation phrase:

```bash
# update + Metamod repair + verification, then exits:
CS2_UPDATER_CONFIRM="UPDATE CS2" docker compose --profile maintenance run --rm cs2-updater
# other modes: CS2_UPDATER_MODE=validate | repair-metamod
```

Always take a backup first (config backup is automatic in `migrate.ps1`).

### Bootstrapping an empty `CS2_DATA_PATH`

SteamCMD delivers only the base game, so a fresh (or wiped) install needs three
maintenance steps in order. `cs2-updater` detects the empty install and downgrades
its Metamod / CounterStrikeSharp checks to warnings for that first run, so the
download is not reported as a failed update:

```bash
# 1. Base game (long download, tens of GB).
CS2_UPDATER_CONFIRM="UPDATE CS2" docker compose --profile maintenance run --rm cs2-updater

# 2. Metamod:Source + CounterStrikeSharp into the persistent install.
docker compose --profile maintenance run --rm cs2-modinstaller

# 3. Restore the gameinfo.gi Metamod search path and verify for real.
CS2_UPDATER_MODE=repair-metamod CS2_UPDATER_CONFIRM="UPDATE CS2" \
  docker compose --profile maintenance run --rm cs2-updater
```

Step 3 must pass before starting a mode; on an already-populated install the addon
checks stay strictly required, so a later update that wipes them still fails loudly.
Mode definitions and plugins live in `manager/modes/` (tracked in git) and are not
affected by any of this — `cs2-modinstaller` leaves them alone unless you pass
`--with-mode-plugins` to re-download the Retakes / MatchZy plugins.

## Rollback

```powershell
./manager/scripts/rollback.ps1 -Backup manager\backups\pre-v3-YYYYMMDD-HHMMSS
```

Config-only: the persistent install and plugin mounts are untouched.

## Security notes

- Panel binds to `127.0.0.1:8080` by default. For remote access use a private VPN
  (WireGuard/Tailscale) or a secured reverse proxy — do not expose it directly.
- The browser never gets a host shell or arbitrary Docker/PowerShell access; only
  known service names and validated operations.
- RCON console commands are risk-classified server-side (ReadOnly / Normal /
  Disruptive / Dangerous / Blocked); `quit`/`exit` are blocked.
- Secrets (GSLT, RCON/server passwords, tokens) are redacted from logs and never
  returned by the API. Auth is currently Basic Auth over localhost; session auth,
  roles and CSRF protection are not yet implemented — do not expose the panel
  directly to an untrusted network.
