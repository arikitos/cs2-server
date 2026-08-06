# Shared frameworks

Metamod and CounterStrikeSharp are shared runtime foundations for every mode.
Their pinned versions are declared in `versions.json` and installed into the
persistent CS2 tree by `install-linux.sh` through the `cs2-modinstaller`
maintenance service.

Framework binaries are intentionally not duplicated in mode directories.
Every mode repeats its required versions in `mode.json`, allowing the runtime to
reject incompatible combinations before deployment.
