# Retake mode

```text
mode.json
packages/
release/plugins/RetakesPlugin/
release/utils/RetakesPluginShared/
release/utils/InstadefusePlugin/
release/utils/InstaplantPlugin/
config/RetakesPlugin.json
cfg/
```

Retakes and Instadefuse have independent component markers. Instaplant is optional and is absent until explicitly installed.

Retakes built-in autoplant is enabled in `config/RetakesPlugin.json`. Disable `BombSettings.IsAutoPlantEnabled` before enabling Instaplant.

Clutch Announce is declared as an optional shared mount.
