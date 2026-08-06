# Retake mode

The Retake mode is self-contained.

```text
mode.json
installed.json
release/plugins/RetakesPlugin/
release/utils/InstadefusePlugin/
release/utils/RetakesPluginShared/
config/RetakesPlugin.json
cfg/
```

Runtime binaries live under `release`. Editable Retakes configuration remains
under `config` and is preserved across package updates.
