#!/usr/bin/env bash
# CS2 Manager V3 — Phase 1 smoke test.
# Confirms the panel API works and that start/restart/switch never run SteamCMD.
# Requires the panel running (scripts/start.sh) and curl.
set -uo pipefail

BASE="${PANEL_URL:-http://127.0.0.1:8080}"
AUTH="${PANEL_AUTH:-admin:301221123}"
PASS=0; FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

call() { curl -s -u "$AUTH" "$@"; }
steamcmd_count() { docker logs "$1" 2>&1 | grep -icE "app_update|steamcmd\.sh|Update state"; }

echo "== status =="
call "$BASE/api/v3/status" | grep -q '"ok":true' && ok "status responds" || bad "status"

echo "== start faceit (no SteamCMD) =="
call -X POST "$BASE/api/v3/server/start" -H 'Content-Type: application/json' -d '{"mode":"faceit"}' >/dev/null
sleep 18
[ "$(steamcmd_count cs2-faceit)" = "0" ] && ok "faceit start: 0 SteamCMD" || bad "faceit start ran SteamCMD"

echo "== restart (no SteamCMD) =="
call -X POST "$BASE/api/v3/server/restart" >/dev/null
sleep 16
[ "$(steamcmd_count cs2-faceit)" = "0" ] && ok "restart: 0 SteamCMD" || bad "restart ran SteamCMD"

echo "== switch to superheroes (no SteamCMD, no MatchZy) =="
call -X POST "$BASE/api/v3/modes/switch" -H 'Content-Type: application/json' -d '{"mode":"superheroes"}' >/dev/null
sleep 16
[ "$(steamcmd_count cs2-superheroes)" = "0" ] && ok "switch: 0 SteamCMD" || bad "switch ran SteamCMD"
[ "$(docker logs cs2-superheroes 2>&1 | grep -ic MatchZy)" = "0" ] && ok "superheroes: MatchZy not loaded" || bad "superheroes loaded MatchZy"

echo "== capacity validation =="
code=$(curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" -X PUT "$BASE/api/v3/modes/superheroes/settings" -H 'Content-Type: application/json' -d '{"capacity":20}')
[ "$code" = "400" ] && ok "superheroes capacity 20 rejected" || bad "capacity 20 accepted ($code)"
code=$(curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" -X PUT "$BASE/api/v3/modes/retake/settings" -H 'Content-Type: application/json' -d '{"active_players":6}')
[ "$code" = "400" ] && ok "retake even active rejected" || bad "retake even accepted ($code)"

echo "== console risk policy =="
code=$(curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" -X POST "$BASE/api/v3/console/command" -H 'Content-Type: application/json' -d '{"command":"quit"}')
[ "$code" = "403" ] && ok "blocked command 'quit' rejected" || bad "quit not blocked ($code)"

echo "== Phase 2: PanelBridge SteamID source =="
call -X POST "$BASE/api/v3/server/start" -H 'Content-Type: application/json' -d '{"mode":"faceit"}' >/dev/null
sleep 18
call "$BASE/api/v3/players" | grep -q '"source":"plugin"' && ok "players use PanelBridge (SteamID64) source" || bad "PanelBridge source not active"
docker exec cs2-faceit sh -c 'true' 2>/dev/null
call -X POST "$BASE/api/v3/console/command" -H 'Content-Type: application/json' -d '{"command":"css_panel_players"}' | grep -q PANELPLAYERS_BEGIN && ok "css_panel_players responds" || bad "css_panel_players missing"

echo "== Phase 2: quick actions + preview =="
call "$BASE/api/v3/modes/faceit/actions" | grep -q '"key":"start"' && ok "faceit actions listed" || bad "faceit actions missing"
call -X POST "$BASE/api/v3/modes/faceit/preview" -H 'Content-Type: application/json' -d '{"capacity":8,"map":"de_mirage"}' | grep -q '"highest_apply_level":"game_restart"' && ok "preview computes apply levels" || bad "preview wrong"
code=$(curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" -X POST "$BASE/api/v3/modes/retake/action" -H 'Content-Type: application/json' -d '{"action":"force_a"}')
[ "$code" = "409" ] && ok "action rejected when mode inactive" || bad "inactive-mode action not guarded ($code)"

echo "== Phase 3: maintenance =="
call "$BASE/api/v3/maintenance/verify-mounts" | grep -q '"all_present":true' && ok "verify-mounts all present" || bad "verify-mounts reported missing"
code=$(curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" -X POST "$BASE/api/v3/maintenance/update" -H 'Content-Type: application/json' -d '{}')
[ "$code" = "403" ] && ok "update requires Owner confirmation" || bad "update not gated ($code)"
BID=$(call -X POST "$BASE/api/v3/maintenance/backup" | grep -oE '"id":"[a-f0-9]+"' | head -1 | cut -d'"' -f4)
sleep 6
call "$BASE/api/v3/maintenance/jobs/$BID" | grep -q '"status":"Succeeded"' && ok "backup job succeeded" || bad "backup job did not succeed"
code=$(curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" -X POST "$BASE/api/v3/maintenance/restore" -H 'Content-Type: application/json' -d '{"confirm":"UPDATE CS2","backup":"../.."}')
[ "$code" = "400" ] && ok "restore rejects path traversal" || bad "restore traversal not blocked ($code)"

echo "== updater refuses without confirmation =="
out=$(docker compose --profile maintenance run --rm -e CS2_UPDATER_CONFIRM="" cs2-updater 2>&1)
echo "$out" | grep -q "Refusing to run" && ok "updater refused without phrase" || bad "updater did not refuse"

call -X POST "$BASE/api/v3/server/stop" >/dev/null
echo ""
echo "RESULT: $PASS passed, $FAIL failed"
exit $([ "$FAIL" = "0" ] && echo 0 || echo 1)
