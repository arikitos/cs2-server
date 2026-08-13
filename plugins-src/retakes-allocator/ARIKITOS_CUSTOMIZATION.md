# Arikitos automatic Retakes customization

This directory contains the source used to build the RetakesAllocator payload bundled with the Retakes mode.

The source is based on [yonilerner/cs2-retakes-allocator](https://github.com/yonilerner/cs2-retakes-allocator) commit `95fad69a89000364ca467add3e78e61e6953d7ff`.

The local customization keeps the upstream allocator architecture and adds two server-managed behaviors.

- Full-buy primary weapon pools allow Terrorists to receive AK-47 rifles and Counter-Terrorists to receive either M4A1-S or M4A4 rifles without player menus.
- Automatic preferred weapon allocation selects at most one random active player across both teams for an AWP when the configured minimum player count is reached.

The mode configuration selects one Pistol round, one HalfBuy round and thirteen FullBuy rounds. Players do not need to run `!awp` or select a weapon preference.

The repository workflow runs the allocator tests and builds `RetakesAllocator/RetakesAllocator.csproj` with .NET 10, matching CounterStrikeSharp API 1.0.371. It removes the server-provided CounterStrikeSharp API assembly, bundles the allocator gamedata, installs the release output under `modes/retakes/addons/counterstrikesharp/plugins/RetakesAllocator` and commits the deployable payload back to `main`.

The upstream SQLite native bundle is pinned to version 2.1.11, the newest release whose `linux-x64` `libe_sqlite3.so` is still built against `GLIBC_2.28`. Version 2.1.12 links against `GLIBC_2.34`, which the Steam Runtime 3 (sniper) game image cannot satisfy because it ships glibc 2.31. With 2.1.12 the allocator aborted during `Load` with `DllNotFoundException`, players received no weapons, and the forced plugin cleanup left a dangling native callback that terminated the server process on the next round-end event.

The pin keeps SQLite 3.49.1, well ahead of the 3.44 series shipped by the previously used 2.1.7. It leaves `SQLitePCLRaw.lib.e_sqlite3` flagged by `NU1903` for [CVE-2025-6965](https://github.com/advisories/GHSA-2m69-gcr7-jv3q). That risk is accepted here: the advisory requires the attacker to inject arbitrary SQL, while this deployment uses a local `data.db` written only by plugin-generated statements, and `AllowedWeaponSelectionTypes` is restricted to `Default` so players cannot store weapon preferences. Closing the advisory outright requires compiling `libe_sqlite3.so` from the SQLite amalgamation inside the runtime image against glibc 2.31.
