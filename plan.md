# CS2 server architecture refactor

## Goal

Replace the package and bridge-directory deployment model with a direct mode layout.
Each `modes/<mode>` directory is an installable overlay whose `addons` and `cfg`
paths map directly to `server/game/csgo`.

The dashboard remains functional during this phase, but visual and interaction
improvements are intentionally deferred to a follow-up pull request.

## Target structure

```text
panel/                 Dashboard backend and current UI
modes/                 Direct release-shaped mode overlays
server/                Persistent CS2 data, runtime, updater, frameworks and tests
install-windows.cmd    Double-click Windows entry point
setup-on-windows.ps1   Windows bootstrap and local setup
compose.yml            One game container, one panel and maintenance services
```

## Decisions

- The supported modes are `matchzy`, `retakes`, `heroshift` and `warcraft`.
- A mode may contain any companion plugin inside its own `addons` tree.
- Activating a mode discovers every file under `addons` and `cfg` automatically.
- No package manifest, source catalog, release directory or mount list is required.
- Switching modes removes only files recorded in the previous deployment inventory.
- Runtime-generated files that were not copied from a mode are preserved.
- Frameworks remain server-wide because Metamod and CounterStrikeSharp are shared runtime foundations.
- Operator state and editable configuration live outside the replaceable mode directories.
- SteamCMD maintenance remains separate from the live server console.

## Work log

- [x] Inspected the existing `main` and `refactor` state.
- [x] Verified the upstream release layouts for MatchZy, Retakes, HeroShift and Warcraft Classic.
- [x] Confirmed that `refactor` starts at `343a847fb86fa37662371ec608ad9c3bcbfac6a1`.
- [x] Move the dashboard backend to `panel` and update its paths.
- [x] Convert all four modes to direct release-shaped overlays.
- [x] Implement automatic, transactional mode deployment and cleanup.
- [x] Move server runtime, updater and framework concerns under `server`.
- [x] Remove the legacy package catalog, fetchers, bridges and stale scripts.
- [x] Update Compose, setup, documentation and CI.
- [x] Run focused and repository-wide verification.
- [x] Review the final diff and publish a draft pull request.

## Verification record

- `python3 -m unittest discover -s server/tests -v`, 16 tests passed.
- `python3 -m py_compile panel/*.py server/runtime/mode_manager.py`, passed.
- Shell syntax checks for runtime, framework, updater and operational scripts, passed.
- All four `mode.json` files parsed and passed the direct-layout repository contract.
- The panel backend imported with isolated Flask and Docker test doubles, discovered
  the four new IDs, wrote runtime cfg files under operator state and seeded the
  Retakes configuration outside the replaceable mode tree.
- A temporary end-to-end deployment switched MatchZy to Retakes, removed the old
  plugin files and preserved an unmanaged framework sentinel.
- `git diff --check`, passed.

## Windows local runtime follow-up

### Goal

Make a fresh clone installable on a local Windows computer with Docker Desktop, without carrying an inactive Raspberry Pi or FEX execution path.

### Work log

- [x] Start a clean branch from the merged `main` state.
- [x] Add a double-click Windows command launcher.
- [x] Make the PowerShell bootstrap compatible with Windows PowerShell and PowerShell 7.
- [x] Start Docker Desktop when installed but not running, then validate Linux `amd64` containers.
- [x] Keep fresh CS2 data under `server/cs2` and preserve an explicitly configured existing data path.
- [x] Remove the unused FEX Dockerfile and launcher branch.
- [x] Update setup references, Windows documentation, CI scope and repository contract tests.
- [x] Run focused and repository-wide verification available in the Linux workspace.
- [x] Review the final diff for stale platform references and accidental edits.
- [x] Publish the branch and open draft pull request [#8](https://github.com/arikitos/cs2-server/pull/8).

### Verification record

- `python3 -m unittest discover -s server/tests -v`, 18 tests passed, including the Windows installer and native runtime repository contracts.
- `python3 -m py_compile panel/*.py server/runtime/mode_manager.py`, passed.
- Shell syntax checks for the runtime, framework, updater and operational scripts, passed.
- `git diff --check`, passed.
- Docker Compose validation and the live installer were not run because this workspace has neither Docker nor Windows PowerShell.

## Open risks

- A live Docker Desktop and CS2 smoke test requires the target Windows computer and cannot be completed in this workspace.
- `setup-on-windows.ps1` cannot be executed here because this Linux workspace does not have Windows PowerShell, Docker Desktop or a persistent CS2 installation.
- Upstream release upgrades may change archive layouts. The direct overlay contract intentionally makes such changes visible instead of normalizing them through hidden adapters.
