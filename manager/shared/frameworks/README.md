# Shared frameworks

Metamod and CounterStrikeSharp are server-wide runtime foundations. Their pinned versions are declared in `versions.json` and installed into the persistent CS2 directory by `install-linux.sh`.

They are deliberately separate from plugin release fetching. Updating to the newest framework without checking plugin API compatibility can prevent one or more modes from loading.

Current contract.

```text
Metamod 2.0.0-git1410
CounterStrikeSharp 1.0.371
```

Install or repair the pinned pair with.

```bash
docker compose --profile maintenance run --rm cs2-modinstaller
```
