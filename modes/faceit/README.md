# FaceIt competitive preset

A local 5v5 competitive preset powered by MatchZy 0.9.1. This name describes the match style; it does not connect the server to the FACEIT platform or its anti-cheat service.

MatchZy controls ready-up, the knife round, competitive rules, tactical and technical pauses, overtime and match backups. The preset requires ten ready players. The panel controls the server name, starting map and map pool, and exposes the MatchZy command catalog through the console.

The release payload is bundled under `addons/`. Version provenance and archive checksums are in `server/frameworks/versions.json`. The upstream `cfg/MatchZy` files are preserved, with `matchzy_minimum_ready_required` set to 10 for this preset. Keep `cfg/mode_faceit.cfg`, `mode.json`, and companion plugins when replacing the upstream payload.

Existing panel settings saved for the old `matchzy` mode are migrated to `faceit` on startup. The format is fixed to 5v5. The persistent CS2 install and the previous managed-file inventory remain in place, so the mode manager removes obsolete mode files transactionally on the next launch.
