# Package inbox and source catalog

The preferred online workflow is.

```powershell
./update.ps1 -FetchLatest -WhatIf
./update.ps1 -FetchLatest
```

`fetch-releases.ps1` reads `sources.json`, downloads approved official GitHub release assets and normalizes their different archive layouts into the local package contract.

## Component inboxes

```text
modes/faceit/matchzy/
modes/retake/retakes/
modes/retake/instadefuse/
modes/retake/instaplant/
modes/heroshift/heroshift/
shared/clutch-announce/
```

Each component has an independent version marker. This allows one plugin to be updated without replacing the other contents of its mode.

## Source selection

Default sources are MatchZy, Retakes, Instadefuse, Clutch Announce and HeroShift.

Instaplant is optional because Retakes has built-in autoplant enabled by default.

```powershell
./fetch-releases.ps1 -Source matchzy
./fetch-releases.ps1 -Mode retake
./fetch-releases.ps1 -SharedOnly
./fetch-releases.ps1 -IncludeOptional -Source instaplant
```

The same parameters can be used through `update.ps1 -FetchLatest`.

## Normalized package contract

```text
package-manifest.json
payload/
```

```json
{
  "schemaVersion": 2,
  "packageType": "mode",
  "id": "faceit",
  "component": "matchzy",
  "name": "MatchZy",
  "version": "0.8.16",
  "payloadRoot": "payload",
  "installStrategy": "replace-roots",
  "installRoots": [
    "plugins/MatchZy"
  ],
  "files": [
    {
      "path": "payload/plugins/MatchZy/MatchZy.dll",
      "size": 1234,
      "sha256": "lowercase-sha256"
    }
  ]
}
```

Rules.

1. Version must be `X.Y.Z` or `vX.Y.Z`.
2. `packageType` must be `mode` or `shared`.
3. `id` and `component` use lowercase letters, numbers and hyphens.
4. Every payload file appears exactly once in `files` with its exact size and SHA256.
5. Every standard package file remains below `payloadRoot`.
6. `replace-roots` requires non-overlapping `installRoots` and every file must remain under one declared root.
7. `replace-release` replaces the complete release directory.
8. Equal or older versions are skipped and no ZIP is removed.
9. After a successful newer install, only lower-version ZIP files for the same component are removed.
10. The active ZIP remains in the inbox.

Existing HeroShift packages with the original verified HeroShift manifest and `addons` layout are accepted directly.
