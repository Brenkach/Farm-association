#!/usr/bin/env bash
# Видалення всіх ресурсів Farm API з LocalStack.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=scripts/common.sh
source scripts/common.sh
require_localstack

API_ID=$(api_id_by_name)
if [ -n "$API_ID" ] && [ "$API_ID" != "None" ]; then
  awsl apigateway delete-rest-api --rest-api-id "$API_ID" && echo "REST API $API_ID видалено"
fi
awsl lambda delete-function --function-name "$FUNCTION_NAME" >/dev/null 2>&1 && echo "Lambda видалено"
awsl iam delete-role-policy --role-name "$ROLE_NAME" --policy-name farm-api-access 2>/dev/null
awsl iam delete-role --role-name "$ROLE_NAME" 2>/dev/null && echo "роль IAM видалено"
awsl dynamodb delete-table --table-name "$TABLE_NAME" >/dev/null 2>&1 && echo "таблицю DynamoDB видалено"
rm -rf build .api-url
echo "Готово"
