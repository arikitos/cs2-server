# HeroShift mode — operator guide

A random skill every round, powered by the **HeroShift** plugin (the
`arikitos/hero-shift` fork of jRandomSkills, currently **v1.0.0**). The
user-facing label is "HeroShift"; the mode's internal id stays `superheroes`
(container `cs2-superheroes`, `SUPERHEROES_CAPACITY`, mode dir `manager/modes/superheroes`).

The mode is isolated: it does **not** load MatchZy, AutoReady, Retakes or
Instadefuse, and normal start/restart/switch never runs SteamCMD. It **does**
require RayTrace (see below).

## Panel controls

HeroShift is a first-class mode in the web panel. HeroShift ships no per-player
hero query/force protocol, so there is no live-player table — the **skill roster
is the control surface**. Per skill the panel exposes a safe subset:

1. **Active** — include or exclude the skill from the random draw.
2. **Rarity** — `Common` · `Uncommon` · `Rare` · `Epic` · `Legendary` · `Mythic`
   (weights the draw chance).
3. **MaxPerServer** — cap concurrent holders (`-1` = unlimited, up to `32`).

Plus a handful of `config.json` toggles: chat-info for your/killer/teammate
skills, end-of-round summary, bot skills, disable-skills-on-round-end, and the
`SkillTimeBeforeStart` / `SkillDescriptionDuration` timings (both now **10s**, up
from 7s, so the skill draw and its description line up with the 10s freeze time).
Skill mechanics, colors and permissions stay as shipped. Saves are validated, backed up
(`*.bak-*`, last 10 kept), written atomically and live-reloaded (`css_reload`)
when the mode is running.

## Roster & config

**125 skills** ship, **124 active** — `Planter` is the one skill turned off. The
editable source of truth (what the panel edits, bind-mounted over the plugin's own
copies) is:

```text
modes/superheroes/mode.json                # the mode definition the panel reads
modes/superheroes/config/skillsInfo.json   # the skill roster
modes/superheroes/config/config.json       # HUD, chat, commands, timings
```

Both config files are declared in `mode.json` under `configs`, which is how the
panel resolves them — along with this mode's plugin list (HeroShift + the RayTrace
util), capacity range, defaults and RCON quick actions.

Both files are kept byte-identical to the plugin's own
`plugins/HeroShift/configs/` copies — mirror any hand edit into both.

**Version numbering:** the fork restarted its releases at **v1.0.0** (2026-07-26),
which supersedes the older `v1.1.0`/`v1.2.0` tags — the number went *down*, the build
did not. Compare release contents, not tag order.

v1.0.0 brings the **multi-language / GeoLite system back** (it had been stripped in
the old v1.1.0). `config.json` carries a `LanguageSystem` block (`DefaultLangCode`
`en`, GeoLite enabled, 10 ISO→file mappings) plus a `ChangeLanguageCommand`
(`!lang` / `!language`, open to everyone), and the plugin ships `MaxMind.Db.dll` +
`packages/GeoLite2-Country.mmdb` for country→language detection. `languages/` now
holds **9 files** — `en`, `he`, `de`, `fr`, `pl`, `pt-br`, `ru`, `tr`, `zh` — each 396
keys, all in sync with `en.json` except `zh.json`, which is missing
`teleporter_desc2`. Two release-side quirks worth knowing: the `LanguageSystem`
mapping for `CZ` points at a `cs` file that **does not ship** (Czech clients fall back
to `en`), and hero display names are deliberately *not* translated — only the
placeholder `None` is localized, so every language shows the same hero names.
Many chat commands also regained their Polish/Portuguese/Chinese aliases.

The plugin writes `plugins/HeroShift/configs/playersLanguage.json` (a SteamID64 →
language map). It is generated state, safe to delete, and comes back on its own — it
was cleared during the v1.0.0 update so the four previously stored players are
re-detected instead of staying pinned to `en`.

The skills' **display names are Marvel heroes** — a rename of
`en.json` values only; the skill keys, roster and mechanics are untouched, so panel
edits carry over. v1.0.0 ships `en.json` byte-identical to the previous build, and an
earlier pass had reshuffled **97** of those names (e.g. `godmode`
"Captain America" → "Juggernaut", `radarhack` → "Professor X", `zeus` → "Surge"),
so a hero name is **not** a stable identifier — always match skills by key/`Name`
in `skillsInfo.json`, never by the localized label.

## Current balance baseline

The shipped roster is deliberately tuned away from upstream defaults; if you diff
against a fresh HeroShift release, expect these to differ on purpose:

- **One holder per skill.** `MaxPerServer` is `1` for 124 of the 125 entries (only
  the placeholder `None` stays `-1`). No two players get the same skill in a round.
- **Rarity spread:** 101 `Common` · 15 `Rare` · 9 `Epic`. `Uncommon`, `Legendary`
  and `Mythic` are unused (still selectable in the panel). The top tier is the
  round-swinging set — `Aimbot`, `AntyHead`, `AreaReaper`, `Cutter`, `InfiniteAmmo`,
  `OneShot`, `RadarHack` were promoted to `Epic`; `KillerFlash` dropped to `Rare`.
- **No instant-kill / infinite-range outliers.** `ThrowingKnife` 9999 → 75 damage,
  `Baseball` 9999 → 80, `DeathBomb` 999 → 80 damage and 500 → 260 radius,
  `LongKnife` reach 4096 → 160 (and friendly fire off), `LongZeus` 4096 → 300.
- **Economy and health capped:** `RichBoy` 5000–15000 → 1500–3500, `Rambo` bonus HP
  50–501 → 25–50, `ReZombie` 500 → 250 HP, `Hermit` +100 → +15 HP, `Medic` heals
  50 → 35 with 2 (was 3) healthshots, `RobinHood` ×35 → ×20.
- **Longer cooldowns on strong skills, shorter on weak ones:** `GodMode` 30 → 45s
  (duration 2 → 1.25s), `Noclip` 30 → 40s (2 → 1s), `EnemySpawn` 15 → 30s,
  `Fortnite` 2 → 10s, `Medic` 1 → 8s, `Regeneration` 0.25 → 1.5s versus `Cypher`
  30 → 15s and `Dash` 2 → 1s.
- Roughly 120 further per-skill numbers (proc chances, radii, speed caps, grenade
  limits, invisibility percentages) were pulled toward the middle. The full list is
  the `skillsInfo.json` diff — treat that file as the record, not this summary.
- **Untuned by design:** the knobs v1.0.0 *added* sit at their shipped defaults —
  `WildThrow` `DeviationMin` 150 / `DeviationMax` 450, `ThrowingKnife` `ThrowForce`
  2000, `Smoker` `RefillInterval` 15.5s, `Replicator`/`Fortnite` `SpawnDistance`
  40 / 50, `Illusionist` `CloneDistance` 40 with `SpeedRun` 3.5 / `SpeedCrouch` 1.25.
  Revisit them if those skills feel off.

## Round settings

HeroShift runs the shared base profile like every other mode:
`mode_superheroes.cfg` execs `manager/shared/cfg/server.cfg` and then adds only the
two convars this mode needs on top of it — `mp_roundtime 1.55` and
`mp_warmuptime 20`. Change a shared value in `server.cfg`, not here.

Panel settings match the other modes: `max_rounds` 24, freeze time **15s**,
`bot_quota` 0, friendly fire off, `de_dust2`, capacity 10. Freeze time is set in
three places that must agree: `data/modes/superheroes.json`, the panel-generated
`modes/superheroes/cfg/panel_runtime.cfg`, and the `!start` vote's `StartParams` in
`config.json`. The panel's Server Config writes the first two; edit the third by
hand.

## RayTrace dependency

Some skills need **RayTrace** (Juzlus/Ray-Trace): a native Metamod module plus
`RayTraceImpl` (CSS plugin) and `RayTraceApi` (CSS shared). It is staged under
`modes/superheroes/utils/RayTrace/addons/` and mounted **only** into this mode so
the others stay clean. This CS2 image reports an empty game dir at Metamod load,
so compose also mounts the gamedata at the absolute path `/addons/RayTrace/gamedata.json`
— do not remove that mount or RayTrace fails to load. Confirm with `meta list`
(native module) and `css_plugins list` (`RayTraceImpl`).

## Updating the plugin

HeroShift is a prebuilt drop-in release (no build script). To update, unzip the
new release over the mode tree, merging:

- `plugins/HeroShift/*` → `modes/superheroes/plugins/HeroShift/` — DLLs,
  `languages/`, `packages/` (the whole directory is bind-mounted, so new files and
  new subdirectories need no compose change)
- `gamedata/HeroShift.gamedata.json` → `modes/superheroes/gamedata/`
- mirror `configs/config.json` + `configs/skillsInfo.json` into the panel
  source-of-truth `modes/superheroes/config/`

Then recreate the game container so the new DLL loads (`css_reload` only reloads
config, not the native binary).

A release ships upstream defaults, so **do not copy its `skillsInfo.json` over the
tuned one** — merge instead, in this order:

1. **Roster:** add/remove whole skill entries so the set matches the release.
2. **Schema:** for every surviving skill, add the properties the release added (at
   their shipped defaults, in the shipped position) and drop ones it removed — a
   release can extend a skill's knobs without touching the roster. v1.0.0 did exactly
   that for six skills; same 125 entries, six new properties.
3. **Values:** keep every locally tuned value above. Verify with a diff that *no*
   pre-existing property changed.

`config.json` is the same story — start from the release copy and re-apply the three
local deviations (`SkillTimeBeforeStart` 10, `SkillDescriptionDuration` 10, and
`mp_freezetime 15` inside the `!start` `StartParams`) so new blocks like
`LanguageSystem` are picked up verbatim. Write both JSONs as UTF-8 **without a BOM**:
the panel reads them with a strict `utf-8` decode and a BOM makes it 500.
`playersLanguage.json` is generated state; there is nothing to merge.

## Build and run

```powershell
# Create the service without running SteamCMD.
docker compose create cs2-superheroes

# Only one game server may own port 27015 — stop the others first.
docker compose stop cs2-faceit cs2-retakes
docker compose up -d cs2-superheroes

# Confirm HeroShift + RayTrace loaded and the roster came up.
docker logs -f cs2-superheroes   # expect "RayTrace MetaMod [OK]" and a "Skills loaded" line
                                 # (124 of 125 active — Planter is intentionally off)
```

## Commands

Skills are assigned automatically each round; players normally just play. Chat
commands use the `!` prefix, console commands use `css_`.

| Command | Access | Effect |
|---|---|---|
| `!hud` / `css_hud` | everyone | Toggle the skill HUD |
| `!lang` / `css_lang` | everyone | Pick a language (overrides GeoLite detection) |
| `!reload` / `css_reload` | `@HeroShift/admin` | Reload `config.json` + `skillsInfo.json` |
| `css_next_skill` | `@HeroShift/admin` | Advance so players are reassigned skills |
| `!setskill` / `!setstaticskill` | `@HeroShift/admin` | Force a skill on a player |
| `!skills` | `@HeroShift/admin` | List / manage skills |
| `!start` · `!swap` · `!shuffle` · `!pause` · `!map` | `@HeroShift/admin` | Match control |
| `!console` · `!setscore` | `@HeroShift/owner` | Server console / set score |

The panel drives HeroShift through `css_reload` and `css_next_skill`.

## Rollback

```powershell
docker compose stop cs2-superheroes
docker compose rm -f cs2-superheroes
```

Restore the previous roster/config from the panel's automatic backups
`modes/superheroes/config/{skillsInfo,config}.json.bak-*`, then recreate the
mode. The shared CS2 installation remains untouched.
