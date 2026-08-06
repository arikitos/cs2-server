# Package inbox

Place versioned ZIP packages in the matching component folder and run
`./update.ps1` from the repository root.

```text
installs/modes/<mode-id>/*.zip
installs/shared/<component-id>/*.zip
```

The updater trusts `package-manifest.json`, not the filename or containing
folder. A standard package uses this structure.

```text
package-manifest.json
payload/
  plugins/
  utils/
  gamedata/
```

The payload contents are installed as the complete `release` directory for the
package identity.

```json
{
  "schemaVersion": 1,
  "packageType": "mode",
  "id": "example-mode",
  "name": "Example Mode",
  "version": "1.2.3",
  "payloadRoot": "payload",
  "files": [
    {
      "path": "payload/plugins/Example/Example.dll",
      "size": 1234,
      "sha256": "lowercase-sha256"
    }
  ]
}
```

Rules.

1. Version must be `X.Y.Z` or `vX.Y.Z`.
2. `packageType` must be `mode` or `shared`.
3. `id` must contain lowercase letters, numbers or hyphens.
4. Every payload file must appear once in `files` with its exact byte size and
   SHA256.
5. Standard package files must remain below `payloadRoot`.
6. A mode ID must already have `manager/modes/<id>/mode.json`.
7. Equal or older versions are skipped and no ZIP is removed.
8. After a successful newer install, only lower-version ZIP files for the same
   package identity are removed. The active ZIP remains in the inbox.

Existing HeroShift packages with the original HeroShift manifest and `addons`
layout are supported directly.
