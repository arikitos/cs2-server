# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Removed

- The **GunGame** mode, in full. Gone: the `cs2-gungame` service and every bind
  mount it declared in `compose.yml`, the whole `manager/modes/gungame/` tree (GG2
  plugin, `GunGameAPI` shared library, the `cfg/gungame/` ladder configs and the
  mode README), `manager/data/modes/gungame.json`, `GUNGAME_CAPACITY` from `.env`
  and `.env.example`, the container name in the Windows entry-point script and
  `manager/scripts/start.sh`, `stop.sh`, `migrate.ps1` and
  `rollback.ps1`, the `GunGame` / `GUNGAME` keys in the panel's plugin-log filter
  (`HeroShift` added in their place, which was missing), and every mention in
  `README.md` and `manager/modes/retake/README.md`. The stack is now three game
  services: `cs2-faceit`, `cs2-retakes`, `cs2-superheroes`. Earlier `Unreleased`
  entries below that mention GunGame are left as written — they record what those
  changes did at the time.

- `RetakesAllocator` from the Retake mode. Retake is now RetakesPlugin +
  Instadefuse only, with `GameSettings.EnableFallbackAllocation` back to its stock
  `true` so RetakesPlugin allocates weapons itself — with the allocator gone and
  that flag left `false`, players would have spawned without guns. The allocator's
  buy-menu cvar file (`cfg/cs2-retakes/retakes.cfg`: `mp_buy_anywhere`,
  `mp_buytime`, `mp_maxmoney`, ...) and its bind mount were removed too, since those
  values are wrong for plain retakes play. `config/RetakesPlugin.json` stays mounted
  as the panel-owned source of truth.
- The duplicate `retake_v2` mode. There is now one Retake mode — mode id `retake`,
  label `Retake`, container `cs2-retakes`, capacity env `RETAKE_CAPACITY`, mode dir
  `manager/modes/retake`, base ruleset `mode_retake.cfg` — built from the richer of
  the two trees: both shipped byte-identical RetakesPlugin / Instadefuse /
  RetakesPluginShared binaries and the same base ruleset, and the surviving one also
  carries the plugins' `lang/` and `map_config/` data plus the panel-owned
  `config/RetakesPlugin.json`. The stack is back to four game services;
  `RETAKE_V2_CAPACITY` is gone from `.env` / `.env.example` and
  `data/modes/retake_v2.json` was removed, its live settings carried into
  `data/modes/retake.json` (capacity 9, max rounds 30, freeze time 9).

### Added

- A shared base server profile, `manager/shared/cfg/server.cfg`: one command set
  every mode runs, modelled on the FaceIt profile. It is bind-mounted into all
  three game services as `csgo/cfg/server.cfg` and declared as a shared `configs`
  entry (`"shared": true`, `"kind": "file"`) in every `mode.json`, so Verify mounts
  covers it. Exec order is `server.cfg` → `mode_<id>.cfg` → `panel_runtime.cfg`, so
  the panel's hot convars still win.

- Declarative mode definitions: every mode now owns a validated
  `manager/modes/<mode-id>/mode.json` naming its container, startup cfgs, capacity
  range, settings defaults, extra convars, plugin/util bind mounts and whitelisted
  RCON quick actions. New `manager/panel/mode_defs.py` loads and validates them —
  path traversal, escaping targets, unknown keys, duplicate ids/containers and
  unsafe cfg/RCON text are all rejected, and one bad manifest is reported instead
  of taking the panel down.
- `/api/v3/status` now serves `mode_order`, per-mode `capacity` ranges, the mode's
  plugin list and `mode_definition_errors`; `/api/v3/modes/<mode>` also returns the
  container, `game_alias`, capacity range and plugin list.
- Panel Rebuild now validates the live mode manifests before building and refuses
  to apply a candidate while a `mode.json` is invalid.

### Changed

- Every mode now runs the same server config. `mode_faceit.cfg`,
  `mode_retake.cfg` and `mode_superheroes.cfg` were reduced to `exec server.cfg`
  plus only what that mode's plugin genuinely needs: FaceIt keeps `tv_enable 1`
  (GOTV), Retake keeps `mp_warmuptime 30`, HeroShift keeps `mp_roundtime 1.55` and
  `mp_warmuptime 20`. Everything else — the competitive ruleset, `bot_quota 0`,
  `mp_autoteambalance 0`, `mp_limitteams 0`, `mp_friendlyfire 0`, `mp_maxrounds 24`,
  `mp_freezetime 15`, `sv_pausable 1`, `sv_cheats 0`, `sv_hibernate_when_empty 0`,
  `mp_restartgame 1` — moved into the shared profile. Note this changes how Retake
  and HeroShift play: both had `mp_autoteambalance 1` and shorter rounds before.

- Panel defaults are aligned to the FaceIt defaults across all modes. Retake goes
  from `max_rounds` 30 / `freezetime` 5 to 24 / 15, HeroShift's `freezetime` from
  10 to 15, in both `mode.json` (`settings.defaults`) and the live
  `manager/data/modes/*.json`. HeroShift's `mp_overtime_enable 1` `extra_cfg` line
  was dropped so its generated `panel_runtime.cfg` matches the others; FaceIt's
  `matchzy_autostart_mode 1` stays, as MatchZy is only mounted there.

- **Player capacity is now the only per-mode difference.** Retake holds 9 (was 7),
  FaceIt and HeroShift hold 10 — set in `RETAKE_CAPACITY` / `FACEIT_CAPACITY` /
  `SUPERHEROES_CAPACITY` in `.env` and `.env.example`, and in each `mode.json`'s
  `settings.defaults.capacity`. Retake's `config/RetakesPlugin.json`
  `GameSettings.MaxPlayers` was already 9 and is unchanged.

- `.env.example`'s `CS2_DATA_PATH` and `MANAGER_PATH` now default to `./server` and
  `./manager` (relative to the project root) instead of an external static host path
  (`C:/Development/CS2/Server` / `C:/Development/CS2/Manager`), matching the repo's
  actual layout described in the README's Project Structure section.

- `.env.example`'s `CS2_SERVERNAME` default is no longer a personal name; it ships
  blank like the other credential fields so the template stays generic for any
  operator.

- The panel's `3 · SERVER CONFIG` card is now per-mode, driven by a new optional
  `server_config` boolean in `mode.json` (defaults to `true`, so FaceIt, GunGame and
  Retake are unaffected). `manager/modes/superheroes/mode.json` sets it to `false`,
  hiding the card for HeroShift, which owns its settings elsewhere. The flag is
  validated in `manager/panel/mode_defs.py`, surfaced through `MODES` and
  `/api/v3/status`'s `mode_meta`, and applied in `templates/index.html`'s
  `renderConfig()`. The form is still rendered into the hidden card so pending-change
  and preview state stay consistent when switching modes.

- `manager/profiles/` is now `manager/modes/`, with folder names matching the panel
  mode ids (`retakes` → `retake`, `retakes-v2` → `retake_v2`, and `mode_retakes.cfg`
  / `mode_retakes_v2.cfg` renamed to match). Each mode's supporting plugins and
  shared libraries moved into that mode's `utils/`: AutoReady, Instadefuse,
  RetakesAllocator, RetakesPluginShared, GunGameAPI and RayTrace (from `raytrace/`
  to `utils/RayTrace/`). `plugins/` now holds only the plugin that defines the mode.
  `PanelBridge` stays a single shared copy in `manager/shared/plugins/` and is
  declared as a util of every mode with `"shared": true`.
- `manager/plugins-src/` is gone: each in-house plugin's C# project now lives with
  the plugin it builds. `AutoReady` → `manager/modes/faceit/utils/AutoReady.src`
  (next to the bind-mounted `utils/AutoReady`, so build output stays out of the
  server's plugin directory) and `PanelBridge` →
  `manager/shared/plugins-src/PanelBridge`, matching its shared binary. Both
  `.csproj` `HintPath`s were re-pointed at the same `Server/.../api` DLL from their
  new depth, both projects are declared as `build.project` in the manifests, and
  `verify-mounts` now reports each source tree. `.gitignore` covers the new
  `bin/`/`obj/` locations.
- The panel no longer hard-codes modes: its `MODES`, plugin aliases, quick actions,
  settings defaults, capacity ranges, per-mode runtime convars, HeroShift config
  paths and `verify-mounts` checks all come from the manifests. `verify-mounts`
  therefore covers every declared mount instead of a hand-maintained subset.
  `PANEL_MODES_DIR` replaces `PANEL_PROFILES_DIR` (the old name is still honoured).
- The dashboard takes its mode list, order and capacity limits from the API instead
  of hard-coded JavaScript lists.
- `install-mods-linux.sh`: `--with-profiles` is now `--with-mode-plugins` (old name
  still accepted) and it refreshes `modes/{retake,faceit}/plugins`. Because helper
  plugins moved to `utils/`, that refresh can no longer delete Instadefuse or
  AutoReady. `migrate.ps1` / `rollback.ps1` back up and restore `manager/modes`.
- `README.md`: new "Mode definitions (`mode.json`)" section with the per-mode layout
  and the steps to add a plugin to a mode; the modes table now lists all five modes
  with their mode id and utils.

### Fixed

- Rebuilt and redeployed `manager/modes/superheroes/plugins/HeroShift/`
  (`HeroShift.dll`, `.deps.json`, `.pdb`, `.xml`, `config/heroes.json`) from
  `C:\Development\cs2-hero-shift` at `17a1ae4` — the `player_make_sound` fix
  (`0b098ba`) plus the green HUD / coloured chat work. `config/heroes.json` is part of
  the plugin payload rather than a bind mount, so it ships with the build; the copy it
  replaced was byte-identical to the pre-change upstream file, so no local edits were
  lost. The previously deployed build aborted the whole
  server process (`exit 134`) the moment a player spawned: `HeroShiftPlugin.Load`
  threw on a user message this CS2 build does not expose, after ~20 event handlers
  were already registered, and the failed unload left native hooks bound to collected
  managed delegates. HeroShift now reaches `Finished loading plugin HeroShift` with
  136 enabled heroes. The build also passes `-p:RayTraceApiPath` at the shared
  `utils/RayTrace/.../shared/RayTraceApi/RayTraceApi.dll`, which the previous build
  lacked ("compiled without RayTraceApi.dll"). `RayTraceApi.dll` is deliberately *not*
  copied into the plugin folder — it loads from `addons/counterstrikesharp/shared/`,
  and a private copy would break shared-type identity with `RayTraceImpl`.

- `cs2-superheroes` could not start: the compose bind source
  `manager/modes/superheroes/gamedata/HeroShift.gamedata.json` was missing from the
  working tree, so Docker auto-created it as an empty *directory* and then refused
  the mount (`not a directory: Are you trying to mount a directory onto a file`)
  because the in-container target is a real file. The file is restored from
  `1ce257e^:manager/profiles/superheroes/gamedata/HeroShift.gamedata.json` — the real
  7-entry signature set (`SmokeGrenadeProjectile_CreateFunc`, `Shoot_Secondary`,
  `SnapViewAngles`, ...), matching the `Successfully loaded 7 game data entries` line
  in every boot where HeroShift loaded. Note this is *not* the same as the inert `{}`
  placeholder in the `Server` tree, which exists only so the other modes don't trip
  over an empty file. The mount source is untracked in git, which is why it can vanish
  and regress — commit it so it always exists.

- The panel reported CounterStrikeSharp as healthy when it was not loaded at all.
  The check was `"plugin" in css.lower()`, and the engine's rejection reply
  (`Unknown command 'css_plugins'!`) contains that substring. Both framework checks
  now reject an unknown-command reply via a shared `command_unknown()` helper, and
  the CounterStrikeSharp check additionally requires evidence of a real listing
  (`[#N:LOADED]` rows or "N plugins loaded"), verified against live output in both
  the loaded and not-loaded states.

- `cs2-updater` no longer reports a successful *fresh* install as a failed update.
  It now detects a bootstrap situation before running SteamCMD (no CS2 binary and
  no Metamod/CounterStrikeSharp present) and downgrades the addon checks in
  `verify_install` to warnings for that run only. The Linux game binary stays
  unconditionally required, and on an already-populated install the addon checks
  remain strictly required, so an update that wipes them still fails loudly and
  the panel still rolls back.
- `manager/scripts/install-mods-linux.sh` worked only under the pre-split repo
  layout: it resolved its root to `manager/` and required a non-existent
  `manager/.env`. It now reads `.env` from the project root, accepts a
  `CS2_DATA_DIR` override so it needs no `.env` at all inside a container, and
  translates a Windows `CS2_DATA_PATH` for WSL / Git Bash.
- The same script unconditionally `rm -rf`'d the git-tracked
  `manager/profiles/{retakes,faceit}/plugins` folders and re-downloaded them.
  That refresh is now opt-in behind `--with-profiles`; the default run installs
  only Metamod + CounterStrikeSharp and leaves pinned profile plugins untouched.
  It also refuses to seed addons into an empty install tree, which would
  otherwise leave a half-install that the updater mistakes for an existing one.

### Added

- New `cs2-modinstaller` maintenance service (`maintenance` profile, no ports,
  stopped by default) that runs `install-mods-linux.sh` inside the runtime image
  against the persistent install, making the Metamod/CounterStrikeSharp step of a
  fresh bootstrap reproducible and portable instead of a host-shell-only script.
  It never runs SteamCMD and never launches the game.
- `README.md`: a "Bootstrapping an empty `CS2_DATA_PATH`" section documenting the
  three ordered maintenance steps (base game → addons → `repair-metamod`).

### Changed

- Corrected `README.md` project-structure description of `server/`: it is the
  host's gitignored CS2 dedicated-server install (`CS2_DATA_PATH`), not an
  empty placeholder.

### Added

- New **GunGame** game mode (`cs2-gungame`), powered by the GG2 plugin v1.2.4
  (`ssypchenko/cs2-gungame`) plus its `GunGameAPI` shared library, staged under
  `manager/profiles/gungame/`. Isolated like every other mode: it mounts only its
  own config and GG2, and normal start / restart / switch never runs SteamCMD.
  It is a first-class panel mode (mode card, Server Config, health chips, log
  source, and `gg_restart` / `gg_config gungame` / `gg_version` / `gg_enable` /
  `gg_disable` / `bot_kick` mode commands), sized by the new `GUNGAME_CAPACITY`
  env var, and runs Casual (`game_type 0` / `game_mode 0`) as GG2 requires.
  Two deliberate deviations from the stock release — `DisableRtvLevel` set to `0`
  and the `ggmc_change_nextmap` line in `gungame.gameend.cfg` commented out —
  because the GunGame MapChooser plugin they depend on is not part of this stack.
  GG2's optional stats database is not configured, so `!rank` / `!top` stay off.

- New **Retakes V2** game mode (`cs2-retakes-v2`), a second Retakes profile
  running the same RetakesPlugin (`B3none/cs2-retakes`) + Instadefuse as the
  existing `retake` mode, plus **RetakesAllocator**
  (`yonilerner/cs2-retakes-allocator`) for round-type-driven weapon/economy
  allocation, staged under `manager/profiles/retakes-v2/`. It is a first-class
  panel mode (mode card, Server Config, health chips, log source, and the same
  bombsite/scramble/queue mode commands as `retake`), sized by the new
  `RETAKE_V2_CAPACITY` env var. Two deliberate deviations required by the
  allocator's setup guide: `RetakesPlugin.json`'s
  `GameSettings.EnableFallbackAllocation` set to `false` (stock default is
  `true`), and a new `cfg/cs2-retakes/retakes.cfg` setting the buy-menu cvars
  (`mp_buy_anywhere`, `mp_buytime`, `mp_maxmoney`, `mp_startmoney`,
  `mp_afterroundmoney`) the allocator needs. RetakesAllocator's compiled
  binaries are not checked into git — see
  `manager/profiles/retakes-v2/plugins/RetakesAllocator/PLACEHOLDER.txt` for
  the manual install step. The existing `retake` mode is untouched.

### Fixed

- Panel no longer retries RCON auth every 2s for up to 90s after a mode start
  when `CS2_RCON_PASSWORD` is unset. Previously this hammered the game server
  with failed RCON logins from the panel's own container IP, tripping CS2's
  "rcon hacking attempts" ban protection and locking the panel out of RCON.

### Changed

- `CS2_SERVERNAME` is now a base name only (e.g. `Arik's`); each game mode
  appends its own profile name in `compose.yml`, producing
  `Arik's Faceit Server`, `Arik's Retake Server`, and `Arik's SuperHero Server`.
