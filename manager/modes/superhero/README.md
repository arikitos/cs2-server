# SuperHero mode

Classic CS 1.6-style SuperHero gameplay implemented as a standalone CounterStrikeSharp plugin.

## Repository contract

- `src/SuperHeroMod` contains the editable source project.
- `release/plugins/SuperHeroMod` contains the runtime DLLs deployed by CS2 Manager.
- `config/SuperHeroMod.json` contains global plugin settings.
- `config/heroes.json` contains the 25-hero MVP catalog.
- `cfg` contains the mode profile and panel-generated runtime settings.
- `mode.json` is the declarative CS2 Manager mode definition.

## Build

```powershell
./manager/modes/superhero/Release.ps1 -Version 0.1.0
```

The script publishes directly into `manager/modes/superhero/release/plugins/SuperHeroMod`.

## Use

Select `SuperHero` in the CS2 Manager panel and start or restart the game container.

Player commands: `!heroes`, `!hero spiderman`, `!myhero`, `!power`, `!drop all`.

Bind example: `bind mouse3 "css_power"`.

The panel action `Reload SuperHero Config` runs `css_shreload`.
