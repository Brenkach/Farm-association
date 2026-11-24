#!/usr/bin/env bash
# Відмова й відновлення екземпляра під навантаженням:
#   0-10 с  — працюють усі три екземпляри
#   10 с    — екземпляр зупиняється (docker compose stop)
#   25 с    — екземпляр запускається знову (docker compose start)
#   до 45 с — спостерігаємо, як він повертається до обробки запитів
# Використання: ./scripts/failover.sh [app2]
set -euo pipefail

cd "$(dirname "$0")/.."
INSTANCE="${1:-app2}"
URL="${URL:-http://localhost:8080/}"

python3 scripts/load.py "$URL" --duration 45 -c 4 &
LOAD_PID=$!

sleep 10
echo ">>> t≈10s: docker compose stop $INSTANCE"
docker compose stop "$INSTANCE" >/dev/null 2>&1

sleep 15
echo ">>> t≈25s: docker compose start $INSTANCE"
docker compose start "$INSTANCE" >/dev/null 2>&1

wait "$LOAD_PID"
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
