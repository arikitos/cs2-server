#!/bin/sh
set -eu
if [ "$(id -u)" = 0 ]; then
    # Initialize only the mount root; avoid recursively scanning the game on every start.
    chown steam:steam /game
    if [ -d /telemetry ]; then chown steam:steam /telemetry; fi
    exec runuser -u steam -- "$0" "$@"
fi
case "${1:-server}" in
  install|update|validate)
    python3 /opt/cs2/install.py "${1:-install}"
    test -x /game/game/bin/linuxsteamrt64/cs2
    grep -q '"buildid"' /game/steamapps/appmanifest_730.acf
    ;;
  repair)
    python3 /opt/cs2/prepare.py
    ;;
  check)
    cd /opt/steamcmd
    ./steamcmd.sh +login anonymous +app_info_update 1 +app_info_print 730 +quit
    ;;
  inspect)
    python3 /opt/cs2/inspection.py
    ;;
  server)
    mkdir -p /home/steam/.steam/sdk64
    ln -sf /opt/steamcmd/linux64/steamclient.so /home/steam/.steam/sdk64/steamclient.so
    exec python3 /opt/cs2/launch.py
    ;;
  *) echo "Unknown operation" >&2; exit 2 ;;
esac
