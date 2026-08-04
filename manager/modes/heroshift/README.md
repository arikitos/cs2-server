# HeroShift mode operator guide

HeroShift is one of the three isolated game modes managed by this repository.
The mode uses the official HeroShift v1.0.0 release package, CounterStrikeSharp
1.0.371, and the bundled RayTrace managed and Linux native runtime.

## Runtime layout

The tracked mode directory contains only the mode definition, cfg files, and the
manager-owned `config/heroshift.json` override file. Plugin binaries, gamedata,
RayTrace, licenses, and package metadata are never maintained here by hand.

The verified installer extracts the release into:

```text
manager/releases/heroshift/v1.0.0/
```

Docker mounts that directory at `release/` inside the HeroShift mode. The mode
manifest deploys these release-owned paths transactionally:

```text
release/plugins/HeroShift
release/gamedata/HeroShift.gamedata.json
release/utils/RayTrace/addons/metamod/RayTrace.vdf
release/utils/RayTrace/addons/RayTrace
release/utils/RayTrace/addons/counterstrikesharp/plugins/RayTraceImpl
release/utils/RayTrace/addons/counterstrikesharp/shared/RayTraceApi
```

Switching away from HeroShift removes only those manager-owned runtime paths.
FaceIt, Retake, the base game, Metamod, and CounterStrikeSharp remain untouched.

## Configuration

HeroShift v1.0.0 reads one override file:

```text
manager/modes/heroshift/config/heroshift.json
```

The minimal tracked file is intentional:

```json
{
  "schemaVersion": 1
}
```

Omitted values use the typed defaults compiled into HeroShift. The removed
`config.json` and `skillsInfo.json` files are legacy formats and are not read by
v1.0.0. The previous tracked values matched the new canonical defaults, so no
server-specific gameplay override was lost during migration.

When HeroShift is active, the panel action named Reload HeroShift Config first
synchronizes `heroshift.json` into the live managed tree and then runs
`css_reload`. Invalid configuration is rejected by the plugin and its previous
valid snapshot remains active.

## Installation and update

The repository includes the verified `HeroShift-v1.0.0.zip` archive and two
installers. From the repository root, use one of these commands.

Windows PowerShell:

```powershell
./manager/scripts/install-heroshift-release.ps1 ./manager/scripts/HeroShift-v1.0.0.zip
```

Linux:

```bash
./manager/scripts/install-heroshift-release.sh ./manager/scripts/HeroShift-v1.0.0.zip
```

The installer verifies the archive hash, verifies every manifest entry, rejects
unsafe ZIP paths, stages the exact runtime layout, backs up older release
overlays, updates `HEROSHIFT_RELEASE_PATH`, and recreates the panel and game
container while preserving whether the game was running.

Fresh runs of `setup.ps1` and `manager/scripts/start.sh` stage the bundled
release automatically when it is missing.

## Runtime verification

Start or switch to HeroShift from the panel. Confirm that HeroShift and
RayTrace appear in plugin health, then run the repository smoke test. A mode
switch always restarts the game process because RayTrace is a native module.

The expected runtime contains 142 built-in skills. English localization is
embedded in `HeroShift.dll`; an external language file is optional.

## Rollback

Installers move previous version directories into timestamped paths under
`manager/backups`. Restore the desired release overlay, update
`HEROSHIFT_RELEASE_PATH` in `.env`, and recreate the panel and game container.
