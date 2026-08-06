# HeroShift mode

HeroShift owns the following content.

```text
mode.json
cfg/
config/heroshift.json
release/
installed.json
```

`release` contains HeroShift, gamedata and all RayTrace runtime dependencies.
It is populated by `update.ps1` from a package placed under
`installs/modes/heroshift`.

The current HeroShift package format is supported directly. Its verified
`addons` paths are converted into this mode's `release` layout during staging.

`config/heroshift.json` is manager-owned and is never replaced by a package
update. This preserves panel and operator changes across releases.
