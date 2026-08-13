# Retakes

The main payload comes from [B3none/cs2-retakes](https://github.com/B3none/cs2-retakes). Extract its `addons` tree here without changing relative paths.

RetakesPluginShared and Instadefuse are bundled in this mode, together with PanelBridge, ClutchAnnounce and a customized build of Yoni's RetakesAllocator.

The bundled Retakes configuration uses its built-in auto-plant behavior. Review that setting before adding a separate Instaplant plugin. Operator changes are stored under `server/state/configs/retakes`.

The allocator runs automatically without player commands or weapon menus. Round one is Pistol, round two is HalfBuy, and every remaining round is FullBuy. Terrorists receive AK-47s, Counter-Terrorists randomly receive an M4A1-S or M4A4, and one random active player across both teams receives an AWP during each FullBuy when at least five players are active.

Retakes executes the bundled `cfg/cs2-retakes/retakes.cfg` after every map start. It uses the official 4v3 format, first to eight wins, a maximum of fifteen rounds, seven seconds of freeze time, no economy, B3none autoplant and Instadefuse. The panel exposes only format, identity and map selection for this mode.

The customized allocator source is stored in `plugins-src/retakes-allocator`. The `Build customized RetakesAllocator` workflow tests the source, builds the release payload and commits the deployable files into this mode whenever the allocator source or configuration changes on `main`.
