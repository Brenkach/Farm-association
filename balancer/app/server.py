"""Контейнерна версія Farm API з ЛР-8.

HTTP-сервер приймає запити, перетворює їх на подію у форматі API Gateway і викликає
той самий Lambda-обробник (serverless/lambda/handler.py). Дані, як і раніше, лежать
у DynamoDB в LocalStack, тому всі екземпляри працюють зі спільною таблицею.

Додаткові маршрути:
    GET /         ідентифікатор екземпляра
    GET /health   перевірка працездатності (сервер + доступ до DynamoDB)
    GET /work     імітація обробки запиту тривалістю ?ms=... (для порівняння пропускної здатності)
"""

import json
import os
import re
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

import handler as lambda_handler

INSTANCE_ID = os.environ.get("INSTANCE_ID") or socket.gethostname()
PORT = int(os.environ.get("PORT", "8000"))
TABLE_NAME = os.environ.get("TABLE_NAME", "farms")
STARTED_AT = time.time()
MAX_WORK_MS = 2000
FARM_ITEM = re.compile(r"^/farms/([^/]+)$")

# окремий клієнт з короткими тайм-аутами: перевірка здоров'я не має зависати
_health_client = boto3.client(
    "dynamodb",
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
    config=Config(connect_timeout=1, read_timeout=1, retries={"max_attempts": 1}),
)


def log(**fields):
    print(json.dumps({"instance": INSTANCE_ID, **fields}, ensure_ascii=False), flush=True)


def ensure_table(timeout_s=60):
    """Створює таблицю farms, якщо її ще немає (кілька екземплярів стартують одночасно)."""
    client = boto3.client("dynamodb", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"))
    deadline = time.time() + timeout_s
    while True:
        try:
            client.describe_table(TableName=TABLE_NAME)
            return
        except ClientError as err:
            if err.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            try:
                client.create_table(
                    TableName=TABLE_NAME,
                    AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                    KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                    BillingMode="PAY_PER_REQUEST",
                )
                log(event="table_created", table=TABLE_NAME)
            except ClientError as create_err:
                # інший екземпляр встиг створити таблицю першим
                if create_err.response["Error"]["Code"] != "ResourceInUseException":
                    raise
            client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
            return
        except BotoCoreError:
            if time.time() > deadline:
                raise
            time.sleep(2)


def to_event(method, path, body):
    """HTTP-запит -> подія API Gateway (проксі-інтеграція), як у ЛР-8."""
    if path == "/farms":
        resource, params = "/farms", None
    else:
        match = FARM_ITEM.match(path)
        if not match:
            return None
        resource, params = "/farms/{id}", {"id": match.group(1)}
    return {
        "httpMethod": method,
        "resource": resource,
        "path": path,
        "pathParameters": params,
        "body": body,
        "isBase64Encoded": False,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "farm-api"

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Instance-Id", INSTANCE_ID)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False))

    # таблиця маршрутів (метод, шлях) -> обробник; решта запитів іде в Lambda-обробник ЛР-8
    ROUTES = {
        ("GET", "/"): "_index",
        ("GET", "/health"): "_health",
        ("GET", "/work"): "_work",
    }

    def _route(self):
        started = time.perf_counter()
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        handler_name = self.ROUTES.get((self.command, path), "_farms")
        getattr(self, handler_name)(path, url.query)
        if path != "/health":
            log(method=self.command, path=path,
                duration_ms=round((time.perf_counter() - started) * 1000, 1))

    def _index(self, _path, _query):
        self._json(200, {
            "instance": INSTANCE_ID,
            "service": "farm-api",
            "uptime_s": round(time.time() - STARTED_AT, 1),
        })

    def _work(self, _path, query):
        ms = parse_qs(query).get("ms", ["100"])[0]
        ms = min(int(ms) if ms.isdigit() else 100, MAX_WORK_MS)
        time.sleep(ms / 1000)
        self._json(200, {"instance": INSTANCE_ID, "work_ms": ms})

    def _farms(self, path, _query):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else None
        event = to_event(self.command, path, body)
        if event is None:
            self._json(404, {"error": "маршрут не знайдено", "instance": INSTANCE_ID})
            return
        result = lambda_handler.handler(event, None)
        self._send(result["statusCode"], result["body"],
                   result["headers"].get("Content-Type", "application/json"))

    def _health(self, _path=None, _query=None):
        try:
            _health_client.describe_table(TableName=TABLE_NAME)
            self._json(200, {"status": "ok", "instance": INSTANCE_ID, "dynamodb": "ok"})
        except (BotoCoreError, ClientError) as err:
            self._json(503, {"status": "fail", "instance": INSTANCE_ID, "dynamodb": type(err).__name__})

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = _route

    def log_message(self, fmt, *args):
        # стандартний лог http.server замінено на JSON-лог у _route
        pass


class Server(HTTPServer):
    # один екземпляр обробляє запити по одному (як один worker);
    # пропускна здатність зростає за рахунок кількості екземплярів за балансувальником
    request_queue_size = 128
    allow_reuse_address = True


def main():
    ensure_table()
    log(event="started", port=PORT)
    Server(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
