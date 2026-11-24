# shellcheck shell=bash disable=SC2034
# Спільні налаштування для сценаріїв розгортання (підключається через source).
# Сумісно з bash 3.2 (стандартний bash у macOS).

ENDPOINT="${LOCALSTACK_ENDPOINT:-http://localhost:4566}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

# LocalStack приймає будь-які ключі; справжні ключі AWS тут не потрібні
export AWS_ACCESS_KEY_ID="test"
export AWS_SECRET_ACCESS_KEY="test"
export AWS_DEFAULT_REGION="$REGION"
export AWS_PAGER=""

TABLE_NAME="farms"
FUNCTION_NAME="farm-api"
ROLE_NAME="farm-api-role"
API_NAME="farm-api"
STAGE="dev"

# усі виклики AWS CLI йдуть у LocalStack, а не в справжній AWS
awsl() {
  aws --endpoint-url "$ENDPOINT" --region "$REGION" "$@"
}

log() {
  printf '\n==> %s\n' "$*"
}

# чекає до 60 с, поки LocalStack відповість (після docker compose up він стартує кілька секунд)
require_localstack() {
  local attempt
  for attempt in $(seq 1 30); do
    if curl -sf "$ENDPOINT/_localstack/health" >/dev/null; then
      return 0
    fi
    [ "$attempt" -eq 1 ] && echo "Очікування LocalStack на $ENDPOINT..."
    sleep 2
  done
  echo "LocalStack недоступний на $ENDPOINT. Запустіть: docker compose up -d" >&2
  exit 1
}

api_id_by_name() {
  awsl apigateway get-rest-apis --query "items[?name=='$API_NAME'].id | [0]" --output text
}
