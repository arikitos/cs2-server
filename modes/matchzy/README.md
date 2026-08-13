# MatchZy

The main payload comes from [shobhit-pathak/MatchZy](https://github.com/shobhit-pathak/MatchZy). Extract the release `addons` and `cfg` directories here without changing their relative paths.

This mode also contains AutoReady, PanelBridge and ClutchAnnounce under the same `addons` tree. Replacing MatchZy does not require moving those companion directories.

Keep `mode.json` and `cfg/mode_matchzy.cfg`. Operator changes to the declared MatchZy config are stored under `server/state/configs/matchzy` and are not written back into this directory.
