# Retakes

The main payload comes from [B3none/cs2-retakes](https://github.com/B3none/cs2-retakes). Extract its `addons` tree here without changing relative paths.

RetakesPluginShared and Instadefuse are bundled in this mode, together with PanelBridge and ClutchAnnounce. Add another companion by placing its normal CounterStrikeSharp release paths below this mode's `addons` directory.

The bundled Retakes configuration uses its built-in auto-plant behavior. Review that setting before adding a separate Instaplant plugin. Operator changes are stored under `server/state/configs/retakes`.

Retakes executes its generated `cfg/cs2-retakes/retakes.cfg` after every map start. That file owns timing, rounds, economy, bots and friendly fire. The panel therefore exposes only format, identity and map selection for this mode. Selecting `5v4` or `4v3` updates the operator copy of `RetakesPlugin.json` before Start.
