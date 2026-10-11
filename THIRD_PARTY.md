# Third-party components

This project preserves the supplied legacy server's transactional mode manager, mode profiles and customized Retakes allocator. The allocator's original [license](runtime/plugins/retakes-allocator/LICENSE) and customization notes are retained with its source.

The Docker runtime downloads fixed releases from their upstream publishers; their licenses remain distributed in their release payloads. No bundled Steam game binaries are committed to this repository.

- Metamod:Source: https://github.com/alliedmodders/metamod-source
- CounterStrikeSharp: https://github.com/roflmuffin/CounterStrikeSharp
- MatchZy: https://github.com/shobhit-pathak/MatchZy
- Retakes: https://github.com/B3none/cs2-retakes
- Instadefuse: https://github.com/B3none/cs2-instadefuse
- RetakesAllocator: https://github.com/yonilerner/cs2-retakes-allocator

Exact runtime component pins and published checksums are recorded in `runtime/components.json`.
