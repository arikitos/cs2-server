# MatchZy

The MatchZy payload is upstream-owned. Replace its `addons` and `cfg/MatchZy` trees directly from the upstream release without panel-specific edits.

The panel does not generate match format, ready count, timing, economy, bots or friendly-fire overrides for this mode. `cfg/MatchZy/config.cfg` is declared non-editable, so an older operator copy under `server/state/configs/matchzy` is ignored. Lifecycle, health, players, logs and official MatchZy commands remain available.

The main payload comes from [shobhit-pathak/MatchZy](https://github.com/shobhit-pathak/MatchZy). Extract the release `addons` and `cfg` directories here without changing their relative paths.

This mode also contains AutoReady, PanelBridge and ClutchAnnounce under the same `addons` tree. Replacing MatchZy does not require moving those companion directories.

Keep `mode.json` and `cfg/mode_matchzy.cfg`. MatchZy configuration remains release-owned, and files under `server/state/configs/matchzy` are not deployed over it.
