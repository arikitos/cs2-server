# HeroShift — Server Installation Guide

HeroShift is a Counter-Strike 2 plugin for CounterStrikeSharp. Every round, each player receives a hero skill — either randomly or assigned by an admin. It includes 146 built-in skills, an in-game WASD skill menu, a configurable HUD, chat announcements, and admin commands with player voting.

Source code and issue tracker: <https://github.com/arikitos/cs2-heroshift>

---

## 1. Before you install

You need a working CS2 dedicated server with:

| Component | Notes |
| --- | --- |
| Metamod:Source | <https://www.sourcemm.net/downloads.php/?branch=master> |
| CounterStrikeSharp | Must be a **.NET 10** runtime build — <https://docs.cssharp.dev/> |

RayTrace is **included** in this archive. You do not need to download it separately.

> **Windows servers.** The bundled RayTrace Metamod module is a Linux binary. Everything else works on Windows, but these skills will do nothing and the console will log one warning at startup: LongZeus, LongKnife, Iana, Cypher, Noclip, Shade, Grapple, and Ricochet, plus the aim check used by the skill-use button.

## 2. Install

1. **Stop the server.**
2. Extract this archive into your CS2 game directory — the folder that already contains `addons`. On a standard install that is:

   ```text
   .../game/csgo/
   ```

3. **Start the server.**

Extracting merges HeroShift's files into your existing `addons` folder. Nothing outside `addons` is replaced.

### What gets installed

```text
addons/counterstrikesharp/gamedata/HeroShift.gamedata.json
addons/counterstrikesharp/plugins/HeroShift/HeroShift.dll
addons/counterstrikesharp/plugins/HeroShift/Newtonsoft.Json.dll
addons/counterstrikesharp/plugins/HeroShift/WASDMenuAPI.dll
addons/counterstrikesharp/plugins/HeroShift/README.md          (this file)
addons/counterstrikesharp/plugins/HeroShift/configs/heroshift.json
addons/counterstrikesharp/plugins/RayTraceImpl/                 RayTrace plugin
addons/counterstrikesharp/shared/RayTraceApi/                   RayTrace shared API
addons/metamod/RayTrace.vdf                                     RayTrace Metamod entry
addons/RayTrace/                                                RayTrace runtime files
package-manifest.json                                           File list with SHA-256 hashes
```

`package-manifest.json` records the size and SHA-256 hash of every packaged file. Keep it if you want to verify your installation later.

## 3. Verify it loaded

In the server console:

```text
css_plugins list
```

HeroShift should appear with its version number.

A few seconds after startup, HeroShift also prints a startup banner to the console. It is the fastest way to confirm a healthy installation and reports:

- the loaded version, the number of registered skills, and whether a newer release exists
- the configuration file actually in use, and its schema version
- the translation source — embedded English, or your external language file
- the WASD menu status and whether the RayTrace capability is available
- the active game mode, HUD duration, and skill button
- a per-dependency check for `Newtonsoft.Json.dll`, `WASDMenuAPI.dll`, `RayTraceApi.dll`, `RayTraceImpl.dll`, `RayTrace.vdf`, and the HeroShift gamedata file

If RayTrace is missing or failed to load, HeroShift prints one warning naming the skills that will be inactive. The rest of the plugin keeps working normally.

## 4. Give yourself admin rights

HeroShift uses CounterStrikeSharp's admin system. Most commands require an admin flag, so set this up before testing.

Edit `addons/counterstrikesharp/configs/admins.json`:

```json
{
  "Server Owner": {
    "identity": "STEAM_1:0:123456789",
    "flags": ["@HeroShift/admin", "@HeroShift/owner"]
  }
}
```

| Flag | Grants |
| --- | --- |
| `@HeroShift/admin` | Everyday admin actions — assigning skills, match control, reload |
| `@HeroShift/owner` | High-trust actions — raw console commands, entity debugging, setting scores |
| `@HeroShift/death` | Controls whether a player's HUD is hidden after death |

You can also make any command public by setting its permission to `""` in `heroshift.json` — see section 6.

## 5. Commands

Every command works from chat with `!` (for example `!skills`) and from the server console as `css_<alias>`.

### Player and admin commands

| Command | What it does | Default permission |
| --- | --- | --- |
| `!t`, `!useSkill` | Use your current skill. With arguments, targets a skill or player instead | `@HeroShift/admin` |
| `!skills` | Open the WASD menu listing all skills | `@HeroShift/admin` |
| `!setskill <player> <skill>` | Give a player a skill for the current round | `@HeroShift/admin` |
| `!setstaticskill <player> <skill>` | Give a player a skill that persists across rounds | `@HeroShift/admin` |
| `!next_skill <player>` | Step a player through the sorted skill list (testing aid) | `@HeroShift/admin` |
| `!heal` | Heal yourself by 100 HP | `@HeroShift/admin` |
| `!sethealth <value>` | Set your own HP | `@HeroShift/admin` |
| `!hud` | Toggle your own skill HUD | *(everyone)* |
| `!reload` | Reload `heroshift.json` and the active language file | `@HeroShift/admin` |
| `!bomb` | Spawn an already-planted, ticking C4 at your feet (test helper) | `@HeroShift/admin` |
| `!botplace` | Teleport a bot to your position (test helper) | `@HeroShift/admin` |
| `!ent <index>` | Check whether an entity is still alive (debug) | `@HeroShift/owner` |
| `!console <command>` | Run a raw server console command | `@HeroShift/owner` |

### Match control and voting

An admin with the listed permission runs these directly. Any other player starts a vote instead, when voting is enabled for that command.

| Command | What it does | Default permission | Vote time | Needed to pass |
| --- | --- | --- | --- | --- |
| `!map <name or workshop id>` | Change map | `@HeroShift/admin` | 25s | 90% |
| `!start` | Start or restart the match | `@HeroShift/admin` | 15s | 60% |
| `!swap` | Swap the CT and T teams | `@HeroShift/admin` | 15s | 90% |
| `!shuffle` | Randomly redistribute players across teams | `@HeroShift/admin` | 15s | 90% |
| `!pause`, `!unpause` | Toggle the match pause | `@HeroShift/admin` | 15s | 60% |
| `!setscore <ct> <t>` | Set the scores | `@HeroShift/owner` | 15s | 90% |

All aliases, permissions, vote times, thresholds, and cooldowns are configurable.

## 6. Configuration

Edit this file:

```text
addons/counterstrikesharp/plugins/HeroShift/configs/heroshift.json
```

**Every default lives inside the plugin.** This file only holds the values you want to change, which is why it ships nearly empty:

```json
{
  "schemaVersion": 2
}
```

Add only what you need. Anything you leave out keeps its built-in default.

### Common settings

```json
{
  "schemaVersion": 2,
  "general": {
    "gameMode": "NoRepeat",
    "language": "en",
    "alternativeSkillButton": "use",
    "skillTimeBeforeStart": 7,
    "skillDescriptionDuration": 7,
    "yourSkillChatInfo": true,
    "killerSkillChatInfo": true,
    "teamMateSkillChatInfo": true,
    "summaryAfterTheRound": true,
    "enableBotSkills": true,
    "curseSkillPerPlayer": 1
  }
}
```

| Setting | Default | What it does |
| --- | --- | --- |
| `gameMode` | `NoRepeat` | How skills are handed out — see the table below |
| `language` | `en` | Which optional language file to load |
| `alternativeSkillButton` | *(none)* | Key that activates manual abilities, for example `use` |
| `skillTimeBeforeStart` | `7` | Seconds after round start before skills activate |
| `skillHudDuration` | `-1` | Seconds the skill name stays on the HUD — `-1` means always |
| `skillDescriptionDuration` | `7` | Seconds the description stays on the HUD |
| `yourSkillChatInfo` | `true` | Announce your own skill in chat |
| `killerSkillChatInfo` | `true` | Announce your killer's skill in chat |
| `teamMateSkillChatInfo` | `true` | Announce teammates' skills in chat |
| `summaryAfterTheRound` | `true` | Print an end-of-round skill summary |
| `enableBotSkills` | `true` | Give bots skills too |
| `disableSkillsOnRoundEnd` | `false` | Turn skills off as soon as the round ends |
| `disableSpectateHUD` | `false` | Hide the HUD while spectating |
| `curseSkillPerPlayer` | *(off)* | Cap how many punishing skills can target the same player |

### Game modes

| Mode | Behavior |
| --- | --- |
| `Normal` | Each player draws an independent random skill each round |
| `TeamSkills` | Every member of a team shares the same skill |
| `SameSkills` | Every player on the server shares the same skill |
| `NoRepeat` *(default)* | Random, but a player does not repeat a skill until the pool is exhausted |
| `FullRandom` | Random with no repeat tracking |
| `Debug` | Development mode for stepping through skills deliberately |

### Turning individual skills off, or tuning them

Skills are keyed by their lowercase id. Open the `!skills` menu in game to see them.

```json
{
  "schemaVersion": 2,
  "skills": {
    "aimbot": { "enabled": false },
    "godmode": { "enabled": false },
    "dwarf": {
      "rarity": "Rare",
      "maxPerServer": 2,
      "options": { "minScale": 0.6, "maxScale": 0.95 }
    }
  }
}
```

| Field | Meaning |
| --- | --- |
| `enabled` | Include or exclude the skill from the draw |
| `color` | HUD color for the skill name |
| `onlyTeam` | Restrict to `None`, `Terrorist`, or `CounterTerrorist` |
| `disableOnFreezeTime` | Block the skill during freeze time |
| `needsTeammates` | Only draw the skill when the player has teammates |
| `requiredPermission` | Admin flag required to receive the skill |
| `hudDuration` | Seconds the skill name stays on the HUD |
| `descriptionHudDuration` | Seconds the description stays on the HUD |
| `maxPerServer` | Maximum simultaneous holders — `-1` means unlimited |
| `rarity` | `Common`, `Uncommon`, `Rare`, `Epic`, or `Legendary` |
| `options` | Values specific to that skill, such as damage, radius, or cooldown |

Rarer tiers are drawn less often. The default weighting is Common 70%, Uncommon 14%, Rare 10%, Epic 5%, Legendary 1%.

### Renaming commands or making them public

```json
{
  "schemaVersion": 2,
  "commands": {
    "hudCommand": { "aliases": ["hud", "hood"], "permission": "" },
    "skillsListCommand": { "aliases": ["skills", "heroes"], "permission": "" }
  }
}
```

An empty `permission` means anyone can use the command.

### Applying changes

Run `!reload` in game or `css_reload` in the console. No restart needed.

The file is validated before it is applied. If anything is wrong, the errors are printed to the console and **your previous working configuration stays active** — a bad edit will not take the server down. The plugin rejects unknown sections and fields, malformed JSON, unknown skill ids and option names, values outside their allowed range, and duplicate command aliases.

## 7. Translations

English is built into the plugin and always works. No language file is required.

To translate or reword text, set `general.language` and create a matching file:

```text
addons/counterstrikesharp/plugins/HeroShift/languages/<code>.json
```

For example, set `"language": "de"` and create `languages/de.json`. Your file is checked first and anything you leave out falls back to English, so you can translate a few lines or the whole thing.

Use the token `CHATCOLORS.RED` where you need the red chat color, since color codes cannot be typed directly into JSON.

## 8. Updating

1. Stop the server.
2. Extract the new archive over the existing installation.
3. Start the server.

Your `configs/heroshift.json` is overwritten by the packaged default. **Back it up before updating** if you have customized it, or keep your settings in version control.

Language files under `languages/` are not part of the archive and are left untouched.

## 9. Uninstalling

Stop the server and delete:

```text
addons/counterstrikesharp/plugins/HeroShift/
addons/counterstrikesharp/gamedata/HeroShift.gamedata.json
```

Remove the RayTrace files as well only if no other plugin uses them:

```text
addons/counterstrikesharp/plugins/RayTraceImpl/
addons/counterstrikesharp/shared/RayTraceApi/
addons/metamod/RayTrace.vdf
addons/RayTrace/
```

## 10. Troubleshooting

| Symptom | What to check |
| --- | --- |
| Plugin does not appear in `css_plugins list` | Confirm CounterStrikeSharp is a **.NET 10** build, and check the console for load errors |
| Commands say you lack permission | Add the `@HeroShift/admin` flag in `addons/counterstrikesharp/configs/admins.json`, or set the command's `permission` to `""` |
| Console warns that RayTrace is missing | Confirm `addons/metamod/RayTrace.vdf` and `addons/RayTrace/` were extracted. On Windows the bundled module is Linux-only and cannot load |
| Config changes have no effect | Run `!reload` and read the console — a validation error means the old configuration is still active |
| No skills are handed out | Check that skills are not all disabled in the `skills` section and that `skillTimeBeforeStart` has elapsed |
| HUD is not visible | Run `!hud` to toggle it, and check the `hud` section and `general.disableSpectateHUD` |
| Chat spam from skill announcements | Turn off `yourSkillChatInfo`, `killerSkillChatInfo`, `teamMateSkillChatInfo`, or `summaryAfterTheRound` |

## Credits

- **D3X** — original plugin author
- **Juzlus** — modifier
- **ByDexterTR** — contributor

HeroShift bundles [RayTrace](https://github.com/FUNPLAY-pro-CS2/Ray-Trace) and a WASD menu implementation.
