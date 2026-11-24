"""Farm API: Lambda-функція за API Gateway (проксі-інтеграція) з таблицею DynamoDB.

Маршрути:
    GET    /farms        список ферм
    POST   /farms        створити ферму   {"name": "...", "region": "...", "area_ha": 12.5}
    GET    /farms/{id}   отримати ферму
    DELETE /farms/{id}   видалити ферму
"""

import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "farms")

# У LocalStack змінну AWS_ENDPOINT_URL задає сам емулятор; у справжньому AWS її немає
_endpoint = os.environ.get("AWS_ENDPOINT_URL")
_dynamodb = boto3.resource("dynamodb", endpoint_url=_endpoint) if _endpoint else boto3.resource("dynamodb")
table = _dynamodb.Table(TABLE_NAME)


def _json_default(value):
    # DynamoDB повертає числа як Decimal
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Unsupported type: {type(value).__name__}")


def _response(status, body=None):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": "" if body is None else json.dumps(body, ensure_ascii=False, default=_json_default),
    }


def _log(event, status, **fields):
    # один JSON-рядок на запит — потрапляє в CloudWatch Logs (/aws/lambda/<функція>)
    record = {
        "method": event.get("httpMethod"),
        "path": event.get("path"),
        "status": status,
        **fields,
    }
    print(json.dumps(record, ensure_ascii=False))


def _parse_body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw, parse_float=Decimal)
    except json.JSONDecodeError:
        return None, "тіло запиту має бути коректним JSON"
    if not isinstance(data, dict):
        return None, "тіло запиту має бути JSON-об'єктом"
    return data, None


def create_farm(event):
    data, error = _parse_body(event)
    if error:
        return _response(400, {"error": error})

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return _response(400, {"error": "поле name обов'язкове і має бути непорожнім рядком"})

    region = data.get("region", "")
    if not isinstance(region, str):
        return _response(400, {"error": "поле region має бути рядком"})

    area = data.get("area_ha")
    if area is not None:
        if isinstance(area, bool) or not isinstance(area, (int, Decimal)) or area < 0:
            return _response(400, {"error": "поле area_ha має бути невід'ємним числом"})
        area = Decimal(str(area))

    item = {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "region": region.strip(),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if area is not None:
        item["area_ha"] = area

    table.put_item(Item=item)
    return _response(201, item)


def list_farms(_event):
    items = []
    kwargs = {}
    while True:
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    items.sort(key=lambda item: item.get("created_at", ""))
    return _response(200, {"items": items, "count": len(items)})


def get_farm(farm_id):
    item = table.get_item(Key={"id": farm_id}).get("Item")
    if item is None:
        return _response(404, {"error": f"ферму {farm_id} не знайдено"})
    return _response(200, item)


def delete_farm(farm_id):
    old = table.delete_item(Key={"id": farm_id}, ReturnValues="ALL_OLD").get("Attributes")
    if old is None:
        return _response(404, {"error": f"ферму {farm_id} не знайдено"})
    return _response(204)


def handler(event, context):
    method = event.get("httpMethod", "")
    farm_id = (event.get("pathParameters") or {}).get("id")
    resource = event.get("resource", "")

    if resource == "/farms":
        routes = {"GET": list_farms, "POST": create_farm}
        action = routes.get(method)
        response = action(event) if action else _response(405, {"error": f"метод {method} не підтримується"})
    elif resource == "/farms/{id}" and farm_id:
        if method == "GET":
            response = get_farm(farm_id)
        elif method == "DELETE":
            response = delete_farm(farm_id)
        else:
            response = _response(405, {"error": f"метод {method} не підтримується"})
    else:
        response = _response(404, {"error": "маршрут не знайдено"})

    _log(event, response["statusCode"], id=farm_id)
    return response
