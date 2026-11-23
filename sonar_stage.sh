#!/usr/bin/env bash
# Перескан SonarQube та вивантаження метрик через REST API для заданих файлів.
# Використання: ./sonar_stage.sh <мітка_етапу> <файл> [файл...]
# Приклад:      ./sonar_stage.sh baseline privacy_god.py audit_trail.py
set -e
TAG="$1"; shift
SONAR_TOKEN=$(grep '^SONAR_TOKEN=' .env | cut -d= -f2)
LOG=/tmp/sonar_scan_$TAG.log
echo ">>> sonar-scanner (Docker), лог: $LOG"
docker run --rm -e SONAR_HOST_URL="http://host.docker.internal:9000" -e SONAR_TOKEN="$SONAR_TOKEN" \
    -v "$(pwd):/usr/src" sonarsource/sonar-scanner-cli > "$LOG" 2>&1 || { tail -20 "$LOG"; exit 1; }
grep "ANALYSIS SUCCESSFUL" "$LOG" | sed 's/^.*INFO  //'
TASK=$(grep -o 'api/ce/task?id=[a-f0-9-]*' "$LOG" | head -1 | cut -d= -f2)
STATUS=""
for i in $(seq 1 30); do
  STATUS=$(curl -s -u "$SONAR_TOKEN:" "http://localhost:9000/api/ce/task?id=$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['task']['status'])")
  [ "$STATUS" = "SUCCESS" ] && break
  sleep 2
done
echo ">>> обробка звіту сервером: $STATUS"
mkdir -p sonar-evidence
KEYS="complexity,cognitive_complexity,ncloc,functions,classes"
for f in "$@"; do
  OUT="sonar-evidence/${TAG}_$(basename "$f").json"
  URL="http://localhost:9000/api/measures/component?component=farm-association:$f&metricKeys=$KEYS"
  echo ">>> curl -u TOKEN: \"$URL\""
  curl -s -u "$SONAR_TOKEN:" "$URL" -o "$OUT"
  python3 -m json.tool "$OUT"
done
curl -s -u "$SONAR_TOKEN:" "http://localhost:9000/api/measures/component?component=farm-association&metricKeys=ncloc,complexity,cognitive_complexity,classes,functions,files" -o "sonar-evidence/${TAG}_project.json"
echo ">>> проєкт загалом збережено: sonar-evidence/${TAG}_project.json"
