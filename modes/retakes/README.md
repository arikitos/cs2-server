# Retakes

The main payload comes from [B3none/cs2-retakes](https://github.com/B3none/cs2-retakes). Extract its `addons` tree here without changing relative paths.

RetakesPluginShared and Instadefuse are bundled in this mode, together with PanelBridge, ClutchAnnounce and a customized build of Yoni's RetakesAllocator.

The bundled Retakes configuration uses its built-in auto-plant behavior. Review that setting before adding a separate Instaplant plugin. Operator changes are stored under `server/state/configs/retakes`.

The allocator runs automatically without player commands, weapon menus, or weapon cards. It follows an official-style five-stage round progression, configured entirely through `RoundLoadoutSequence` in the allocator's `config.json` (one-based round numbers, each stage's `ToRound` set to `null` for the final open-ended stage):

1. Round 1: Terrorists receive a Glock, Counter-Terrorists receive a USP-S. No primary weapon.
2. Round 2: each player randomly receives one secondary from a team-specific pool (Deagle/P250/Tec9 for Terrorists, Deagle/P250/Five-Seven for Counter-Terrorists). No primary weapon.
3. Round 3: each player randomly receives one SMG-class primary (Mac-10/MP7 for Terrorists, MP9/MP7 for Counter-Terrorists) plus their team pistol.
4. Round 4: each player randomly receives one mid-tier rifle (SSG 08/Galil for Terrorists, SSG 08/Famas for Counter-Terrorists) plus their team pistol.
5. Round 5 until the match ends: Terrorists receive an AK-47, Counter-Terrorists randomly receive an M4A4 or M4A1-S, both plus their team pistol. Each round has a 25% chance of containing an AWP; when it does, one active player across both teams is chosen at random to receive it instead of their team rifle. In the remaining rounds every player keeps their team rifle.

Administrators can retune every stage's weapon pools, round ranges, the preferred-weapon (AWP) cap, and its per-round chance (`PreferredWeaponChance`, 0-100) by editing `RoundLoadoutSequence` without rebuilding the plugin.

Retakes executes the bundled `cfg/cs2-retakes/retakes.cfg` after every map start. It uses the official 4v3 format, first to eight wins, a maximum of fifteen rounds, no freeze time, no economy, B3none autoplant and Instadefuse. The panel exposes only format, identity and map selection for this mode.

The customized allocator source is stored in `plugins-src/retakes-allocator`. The `Build customized RetakesAllocator` workflow tests the source, builds the release payload and commits the deployable files into this mode whenever the allocator source or configuration changes on `main`.
