#!/usr/bin/env bash
# Порівняння роботи з балансуванням (nginx, порт 8080) і без нього (лише app1, порт 8001).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
LB="http://localhost:8080"
DIRECT="http://localhost:8001"

section() {
  printf '\n==================== %s ====================\n' "$*"
}

section "1. Розподіл запитів: без балансувальника"
python3 scripts/load.py "$DIRECT/" -n 300 -c 10

section "1. Розподіл запитів: через балансувальник"
python3 scripts/load.py "$LB/" -n 300 -c 10

section "2. Пропускна здатність (запит обробляється 100 мс): без балансувальника"
python3 scripts/load.py "$DIRECT/work?ms=100" -n 120 -c 12

section "2. Пропускна здатність (запит обробляється 100 мс): через балансувальник"
python3 scripts/load.py "$LB/work?ms=100" -n 120 -c 12

section "3. Відмова екземпляра app1"
docker compose stop app1 >/dev/null 2>&1
echo "app1 зупинено"

section "3. Без балансувальника (app1 недоступний)"
python3 scripts/load.py "$DIRECT/" -n 60 -c 5 --timeout 2

section "3. Через балансувальник (app1 недоступний)"
python3 scripts/load.py "$LB/" -n 60 -c 5 --timeout 2

docker compose start app1 >/dev/null 2>&1
echo
echo "app1 знову запущено"
