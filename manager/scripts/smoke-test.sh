#!/usr/bin/env bash
# Requires a configured, running panel and an installed CS2 server.
set -uo pipefail
BASE="${PANEL_URL:-http://127.0.0.1:8080}"
AUTH="${PANEL_AUTH:-admin:change-me}"
PASS=0; FAIL=0
ok() { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
call() { curl -sS -u "$AUTH" "$@"; }
steamcmd_count() { docker logs cs2-game 2>&1 | grep -icE "app_update|steamcmd\.sh|Update state" || true; }

call "$BASE/api/v3/status" | grep -q '"ok":true' && ok "status responds" || bad "status"

call -X POST "$BASE/api/v3/modes/switch" -H 'Content-Type: application/json' -d '{"mode":"faceit"}' >/dev/null
sleep 18
[ "$(steamcmd_count)" = "0" ] && ok "FaceIt start runs no SteamCMD" || bad "FaceIt start ran SteamCMD"
[ "$(docker ps --format '{{.Names}}' | grep -c '^cs2-game$')" = "1" ] && ok "one game container" || bad "cs2-game is not the sole running game container"

docker exec cs2-game test -d /home/steam/cs2-dedicated/game/csgo/addons/counterstrikesharp/plugins/MatchZy \
  && ok "FaceIt overlay deployed" || bad "MatchZy missing"

call -X POST "$BASE/api/v3/modes/switch" -H 'Content-Type: application/json' -d '{"mode":"heroshift"}' >/dev/null
sleep 18
docker exec cs2-game test ! -e /home/steam/cs2-dedicated/game/csgo/addons/counterstrikesharp/plugins/MatchZy \
  && ok "previous mode removed" || bad "MatchZy leaked into HeroShift"
docker exec cs2-game test -f /home/steam/cs2-dedicated/game/csgo/addons/metamod/RayTrace.vdf \
  && ok "RayTrace deployed for HeroShift" || bad "RayTrace missing"

call -X POST "$BASE/api/v3/modes/switch" -H 'Content-Type: application/json' -d '{"mode":"retake"}' >/dev/null
sleep 18
docker exec cs2-game test ! -e /home/steam/cs2-dedicated/game/csgo/addons/metamod/RayTrace.vdf \
  && ok "RayTrace removed outside HeroShift" || bad "RayTrace leaked into Retake"
docker exec cs2-game test -d /home/steam/cs2-dedicated/game/csgo/addons/counterstrikesharp/plugins/RetakesPlugin \
  && ok "Retake overlay deployed" || bad "RetakesPlugin missing"

code=$(curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" -X PUT "$BASE/api/v3/modes/retake/settings" -H 'Content-Type: application/json' -d '{"capacity":20}')
[ "$code" = "400" ] && ok "capacity validation" || bad "invalid capacity accepted"

call "$BASE/api/v3/maintenance/verify-mounts" | grep -q '"all_present":true' \
  && ok "manifest sources and versions verified" || bad "verify-mounts failed"

call -X POST "$BASE/api/v3/server/stop" >/dev/null
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
