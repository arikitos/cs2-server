#!/usr/bin/env bash
# Requires a configured server and PANEL_AUTH in username:password form.
set -uo pipefail

BASE="${PANEL_URL:-http://127.0.0.1:8080}"
AUTH="${PANEL_AUTH:?Set PANEL_AUTH to username:password}"
PASS=0
FAIL=0

ok() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }
call() { curl -fsS -u "${AUTH}" "$@"; }
steamcmd_count() { docker logs cs2-game 2>&1 | grep -icE "app_update|steamcmd\.sh|Update state" || true; }

call "${BASE}/api/v3/status" | grep -q '"ok":true' && ok "status responds" || bad "status"

call -X POST "${BASE}/api/v3/modes/switch" -H 'Content-Type: application/json' -d '{"mode":"matchzy"}' >/dev/null
sleep 18
[[ "$(steamcmd_count)" == "0" ]] && ok "game start runs no SteamCMD" || bad "SteamCMD appeared in game logs"
docker exec cs2-game test -f /home/steam/cs2-dedicated/game/csgo/addons/counterstrikesharp/plugins/MatchZy/MatchZy.dll \
  && ok "MatchZy deployed" || bad "MatchZy missing"

call -X POST "${BASE}/api/v3/modes/switch" -H 'Content-Type: application/json' -d '{"mode":"heroshift"}' >/dev/null
sleep 18
docker exec cs2-game test ! -e /home/steam/cs2-dedicated/game/csgo/addons/counterstrikesharp/plugins/MatchZy/MatchZy.dll \
  && ok "previous mode removed" || bad "MatchZy leaked into HeroShift"
docker exec cs2-game test -f /home/steam/cs2-dedicated/game/csgo/addons/metamod/RayTrace.vdf \
  && ok "RayTrace deployed" || bad "RayTrace missing"

call -X POST "${BASE}/api/v3/modes/switch" -H 'Content-Type: application/json' -d '{"mode":"retakes"}' >/dev/null
sleep 18
docker exec cs2-game test ! -e /home/steam/cs2-dedicated/game/csgo/addons/metamod/RayTrace.vdf \
  && ok "HeroShift utility removed" || bad "RayTrace leaked into Retakes"
docker exec cs2-game test -f /home/steam/cs2-dedicated/game/csgo/addons/counterstrikesharp/plugins/RetakesPlugin/RetakesPlugin.dll \
  && ok "Retakes deployed" || bad "RetakesPlugin missing"

call "${BASE}/api/v3/maintenance/verify-mounts" | grep -q '"all_present":true' \
  && ok "mode payloads and versions verified" || bad "payload verification failed"
call -X POST "${BASE}/api/v3/server/stop" >/dev/null

echo "RESULT: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" == "0" ]]
