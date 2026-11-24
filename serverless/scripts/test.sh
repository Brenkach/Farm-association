#!/usr/bin/env bash
# Перевірка Farm API через HTTP: створення, отримання, список, видалення, помилки.
set -euo pipefail

cd "$(dirname "$0")/.."
if [ ! -f .api-url ]; then
  echo "Файл .api-url не знайдено. Спершу запустіть scripts/deploy.sh" >&2
  exit 1
fi
ROOT="$(cat .api-url)"
BASE="$ROOT/farms"
FAILED=0

# виконує запит, друкує відповідь і перевіряє код статусу
request() {
  local expected=$1 method=$2 url=$3 body=${4:-}
  local args=(-s -o /tmp/farm-api-body -w '%{http_code}' -X "$method" "$url")
  if [ -n "$body" ]; then
    args+=(-H 'Content-Type: application/json' -d "$body")
  fi
  local code
  code=$(curl "${args[@]}")
  printf '\n%s %s -> %s (очікувано %s)\n' "$method" "${url#"$ROOT"}" "$code" "$expected"
  cat /tmp/farm-api-body
  echo
  if [ "$code" != "$expected" ]; then
    echo "!! неочікуваний статус" >&2
    FAILED=1
  fi
}

echo "API: $BASE"

request 201 POST "$BASE" '{"name": "Зелена долина", "region": "Чернівецька", "area_ha": 120.5}'
FARM_ID=$(python3 -c 'import json; print(json.load(open("/tmp/farm-api-body"))["id"])')

request 201 POST "$BASE" '{"name": "Сонячна ферма", "region": "Вінницька"}'
request 200 GET "$BASE"
request 200 GET "$BASE/$FARM_ID"
request 400 POST "$BASE" '{"region": "без назви"}'
request 400 POST "$BASE" 'не JSON'
request 204 DELETE "$BASE/$FARM_ID"
request 404 GET "$BASE/$FARM_ID"
request 404 DELETE "$BASE/$FARM_ID"

echo
if [ "$FAILED" -eq 0 ]; then
  echo "Усі перевірки пройдено"
else
  echo "Є неочікувані відповіді" >&2
  exit 1
fi
