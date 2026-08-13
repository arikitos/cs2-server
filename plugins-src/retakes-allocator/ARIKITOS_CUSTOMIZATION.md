# Arikitos automatic Retakes customization

This directory contains the source used to build the RetakesAllocator payload bundled with the Retakes mode.

The source is based on [yonilerner/cs2-retakes-allocator](https://github.com/yonilerner/cs2-retakes-allocator) commit `95fad69a89000364ca467add3e78e61e6953d7ff`.

The local customization keeps the upstream allocator architecture and adds two server-managed behaviors.

- Full-buy primary weapon pools allow Terrorists to receive AK-47 rifles and Counter-Terrorists to receive either M4A1-S or M4A4 rifles without player menus.
- Automatic preferred weapon allocation selects at most one random active player across both teams for an AWP when the configured minimum player count is reached.

The mode configuration selects one Pistol round, one HalfBuy round and thirteen FullBuy rounds. Players do not need to run `!awp` or select a weapon preference.

The repository workflow runs the allocator tests and builds `RetakesAllocator/RetakesAllocator.csproj` with .NET 10, matching CounterStrikeSharp API 1.0.371. It removes the server-provided CounterStrikeSharp API assembly, bundles the allocator gamedata, installs the release output under `modes/retakes/addons/counterstrikesharp/plugins/RetakesAllocator` and commits the deployable payload back to `main`.

The upstream SQLite native bundle is pinned to version 2.1.12 so clean builds do not restore the vulnerable 2.1.7 native library.
