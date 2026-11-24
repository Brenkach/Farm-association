#!/usr/bin/env bash
# Розгортання Farm API у LocalStack: DynamoDB -> IAM -> Lambda -> API Gateway.
# Повторний запуск безпечний: таблиця й роль перевикористовуються, код Lambda оновлюється,
# REST API створюється заново.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/common.sh
source scripts/common.sh

require_localstack
ACCOUNT_ID=$(awsl sts get-caller-identity --query Account --output text)

# ---------- 1. DynamoDB ----------
log "1/5 Таблиця DynamoDB '$TABLE_NAME'"
if awsl dynamodb describe-table --table-name "$TABLE_NAME" >/dev/null 2>&1; then
  echo "таблиця вже існує"
else
  awsl dynamodb create-table \
    --table-name "$TABLE_NAME" \
    --attribute-definitions AttributeName=id,AttributeType=S \
    --key-schema AttributeName=id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null
  awsl dynamodb wait table-exists --table-name "$TABLE_NAME"
  echo "таблицю створено"
fi

# ---------- 2. IAM ----------
log "2/5 Роль IAM '$ROLE_NAME'"
if ROLE_ARN=$(awsl iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text 2>/dev/null); then
  echo "роль вже існує"
else
  ROLE_ARN=$(awsl iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document file://iam/trust-policy.json \
    --query Role.Arn --output text)
  echo "роль створено"
fi
awsl iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name farm-api-access \
  --policy-document file://iam/farm-api-policy.json
echo "$ROLE_ARN"

# ---------- 3. Lambda ----------
log "3/5 Lambda-функція '$FUNCTION_NAME'"
rm -rf build && mkdir -p build
(cd lambda && zip -q ../build/function.zip handler.py)

# архітектура функції збігається з процесором хоста (Apple Silicon -> arm64)
case "$(uname -m)" in
  arm64 | aarch64) ARCH="arm64" ;;
  *) ARCH="x86_64" ;;
esac

if awsl lambda get-function --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  awsl lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://build/function.zip >/dev/null
  awsl lambda wait function-updated-v2 --function-name "$FUNCTION_NAME"
  echo "код функції оновлено"
else
  awsl lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --architectures "$ARCH" \
    --handler handler.handler \
    --role "$ROLE_ARN" \
    --zip-file fileb://build/function.zip \
    --timeout 10 \
    --memory-size 128 \
    --environment "Variables={TABLE_NAME=$TABLE_NAME}" >/dev/null
  awsl lambda wait function-active-v2 --function-name "$FUNCTION_NAME"
  echo "функцію створено ($ARCH)"
fi
FUNCTION_ARN=$(awsl lambda get-function --function-name "$FUNCTION_NAME" \
  --query Configuration.FunctionArn --output text)
echo "$FUNCTION_ARN"

# ---------- 4. API Gateway ----------
log "4/5 REST API '$API_NAME'"
OLD_API_ID=$(api_id_by_name)
if [ -n "$OLD_API_ID" ] && [ "$OLD_API_ID" != "None" ]; then
  awsl apigateway delete-rest-api --rest-api-id "$OLD_API_ID"
  echo "попередній API $OLD_API_ID видалено"
fi

API_ID=$(awsl apigateway create-rest-api --name "$API_NAME" \
  --endpoint-configuration types=REGIONAL --query id --output text)
ROOT_ID=$(awsl apigateway get-resources --rest-api-id "$API_ID" \
  --query "items[?path=='/'].id | [0]" --output text)
FARMS_ID=$(awsl apigateway create-resource --rest-api-id "$API_ID" \
  --parent-id "$ROOT_ID" --path-part farms --query id --output text)
FARM_ID=$(awsl apigateway create-resource --rest-api-id "$API_ID" \
  --parent-id "$FARMS_ID" --path-part '{id}' --query id --output text)

INTEGRATION_URI="arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${FUNCTION_ARN}/invocations"

# метод + проксі-інтеграція з Lambda (AWS_PROXY: увесь запит передається у функцію як подія)
add_method() {
  local resource_id=$1 http_method=$2 params=$3
  # shellcheck disable=SC2086  # $params навмисно розбивається на окремі аргументи
  awsl apigateway put-method --rest-api-id "$API_ID" --resource-id "$resource_id" \
    --http-method "$http_method" --authorization-type NONE $params >/dev/null
  awsl apigateway put-integration --rest-api-id "$API_ID" --resource-id "$resource_id" \
    --http-method "$http_method" --type AWS_PROXY --integration-http-method POST \
    --uri "$INTEGRATION_URI" >/dev/null
  echo "  $http_method $(awsl apigateway get-resource --rest-api-id "$API_ID" \
    --resource-id "$resource_id" --query path --output text)"
}

ID_PARAM="--request-parameters method.request.path.id=true"
add_method "$FARMS_ID" GET ""
add_method "$FARMS_ID" POST ""
add_method "$FARM_ID" GET "$ID_PARAM"
add_method "$FARM_ID" DELETE "$ID_PARAM"

# дозвіл API Gateway викликати функцію
awsl lambda remove-permission --function-name "$FUNCTION_NAME" \
  --statement-id apigateway-invoke >/dev/null 2>&1 || true
awsl lambda add-permission --function-name "$FUNCTION_NAME" \
  --statement-id apigateway-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*/*" >/dev/null

# ---------- 5. Deployment ----------
log "5/5 Публікація API на стейдж '$STAGE'"
awsl apigateway create-deployment --rest-api-id "$API_ID" --stage-name "$STAGE" >/dev/null

API_URL="${ENDPOINT}/restapis/${API_ID}/${STAGE}/_user_request_"
echo "$API_URL" > .api-url

log "Готово"
echo "API ID:  $API_ID"
echo "URL:     $API_URL/farms"
echo "Альтернативний URL: http://${API_ID}.execute-api.localhost.localstack.cloud:4566/${STAGE}/farms"
