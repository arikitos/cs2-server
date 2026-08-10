# Warcraft Classic mode

This mode runs the four-race Warcraft Classic plugin from `arikitos/cs2-warcraft3` on the manager-wide Metamod and CounterStrikeSharp versions.

The vendored runtime is built from the exact commit recorded in `vendor.json`. Changing that marker triggers the `Vendor Warcraft Classic` workflow, which publishes the plugin, validates the mode definition and commits the resulting runtime back to `main`.

WarcraftClassic is deployed with granular file mounts rather than mounting the whole plugin directory. The plugin-created `data` directory is therefore not part of the manager inventory and survives switches to FaceIt, Retake or HeroShift. Operator configuration is stored under `config/WarcraftClassic.json` and deployed to the CounterStrikeSharp plugin config location.

The mode keeps the same shared `PanelBridge` integration and optional `ClutchAnnounce` component used by the other modes.
