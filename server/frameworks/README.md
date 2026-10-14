# Pinned frameworks

`versions.json` records exact release versions, download URLs and archive SHA-256 hashes for Metamod, CounterStrikeSharp, MatchZy and Retakes. MatchZy and Retakes are vendored in their mode directories; the installer installs the two shared frameworks.

The installer downloads and verifies both archives in a temporary directory before copying them into the persistent game installation. CounterStrikeSharp includes its .NET 10 Linux runtime. Existing plugin payloads remain owned by the transactional mode manager.

Run only while the game is stopped:

```bash
docker compose stop cs2-game
docker compose --profile maintenance run --rm cs2-modinstaller
docker compose --profile maintenance run --rm \
  -e CS2_UPDATER_MODE=repair-metamod -e 'CS2_UPDATER_CONFIRM=UPDATE CS2' cs2-updater
```

The panel refuses to deploy a preset when its required framework versions differ from the installed version marker. Update the requirements in both mode manifests when changing shared framework versions.
