# HeroShift mode

```text
mode.json
packages/heroshift.json
cfg/
config/heroshift.json
release/
```

The HeroShift package owns the complete `release` directory, including HeroShift, gamedata and RayTrace runtime dependencies.

The original verified HeroShift ZIP format is supported directly. Its `addons` paths are converted into this mode's release layout during staging.

`config/heroshift.json` is manager-owned and is never replaced by a package update.

Clutch Announce is declared as an optional shared mount.
