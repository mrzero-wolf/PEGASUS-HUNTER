#!/usr/bin/env bash
# language: bash, file: start.sh
# Launcher — server or client, backgrounded with nohup.
MODE="${1:-client}"
C2="${C2_URL:-http://127.0.0.1:8080}"

case "$MODE" in
  server)
    nohup python3 server/server.py --host 0.0.0.0 --port 8080 >/tmp/pl_server.log 2>&1 &
    echo "[+] server pid $!  log /tmp/pl_server.log"
    ;;
  client)
    nohup env C2_URL="$C2" python3 client/client.py >/dev/null 2>&1 &
    disown
    echo "[+] client running against $C2"
    ;;
  *) echo "usage: $0 {server|client}"; exit 1;;
esac
