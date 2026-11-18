"""Метрики Prometheus, JSON-логи та імітація помилок (FAIL_RATE).

Підключення в app.py:
    from observability import init_observability
    init_observability(app, APP_VERSION)
"""

import json
import logging
import os
import random
import socket
import sys
import threading
import time
from datetime import datetime, timezone

from flask import Response, g, jsonify, request

# межі кошиків гістограми тривалості запитів, секунди
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
# ці маршрути не ламаються FAIL_RATE і не потрапляють у логи запитів
SKIP_PATHS = ("/metrics", "/health")
KNOWN_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class Metrics:
    """Лічильник і гістограма без сторонніх бібліотек (формат Prometheus)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._requests = {}  # (method, route, status) -> кількість
        self._buckets = {}  # (method, route) -> лічильники кошиків
        self._sums = {}  # (method, route) -> сума тривалостей
        self._counts = {}  # (method, route) -> кількість спостережень

    def observe(self, method, route, status, duration):
        with self._lock:
            key = (method, route, status)
            self._requests[key] = self._requests.get(key, 0) + 1
            hkey = (method, route)
            buckets = self._buckets.setdefault(hkey, [0] * len(BUCKETS))
            for i, bound in enumerate(BUCKETS):
                if duration <= bound:
                    buckets[i] += 1
            self._sums[hkey] = self._sums.get(hkey, 0.0) + duration
            self._counts[hkey] = self._counts.get(hkey, 0) + 1

    def render(self, version):
        lines = [
            "# HELP farm_app_info Information about the running application.",
            "# TYPE farm_app_info gauge",
            f'farm_app_info{{version="{version}"}} 1',
            "# HELP http_requests_total Total number of HTTP requests.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (method, route, status), value in sorted(self._requests.items()):
                labels = f'method="{method}",route="{route}",status="{status}"'
                lines.append(f"http_requests_total{{{labels}}} {value}")
            lines += [
                "# HELP http_request_duration_seconds HTTP request duration.",
                "# TYPE http_request_duration_seconds histogram",
            ]
            for (method, route), buckets in sorted(self._buckets.items()):
                base = f'method="{method}",route="{route}"'
                for i, bound in enumerate(BUCKETS):
                    lines.append(
                        "http_request_duration_seconds_bucket"
                        f'{{{base},le="{bound}"}} {buckets[i]}'
                    )
                count = self._counts[(method, route)]
                total = self._sums[(method, route)]
                lines.append(
                    f'http_request_duration_seconds_bucket{{{base},le="+Inf"}} {count}'
                )
                lines.append(f"http_request_duration_seconds_sum{{{base}}} {total}")
                lines.append(f"http_request_duration_seconds_count{{{base}}} {count}")
        return "\n".join(lines) + "\n"


class JsonFormatter(logging.Formatter):
    """Один JSON-об'єкт на рядок: його розбирає Loki (| json)."""

    def __init__(self, version):
        super().__init__()
        self.version = version
        self.pod = socket.gethostname()

    def format(self, record):
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "version": self.version,
            "pod": self.pod,
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, ensure_ascii=False)


def _setup_logging(version):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(version))
    logger = logging.getLogger("farm")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # текстові access-логи werkzeug замінюємо власними JSON-логами
    logging.getLogger("werkzeug").disabled = True
    return logger


def init_observability(app, version):
    metrics = Metrics()
    logger = _setup_logging(version)
    fail_rate = float(os.getenv("FAIL_RATE", "0") or 0)
    logger.info("application started", extra={"fields": {"fail_rate": fail_rate}})

    @app.before_request
    def _start_timer():
        g.request_start = time.perf_counter()
        failing = fail_rate > 0 and request.path not in SKIP_PATHS
        if failing and random.random() < fail_rate:
            return jsonify(error="simulated failure (FAIL_RATE)"), 500
        return None

    @app.after_request
    def _record(response):
        if request.path == "/metrics":
            return response
        duration = time.perf_counter() - g.get("request_start", time.perf_counter())
        # шаблон маршруту (/farms/<int:id>), а не конкретний URL: мала кардинальність
        route = request.url_rule.rule if request.url_rule else "unmatched"
        method = request.method if request.method in KNOWN_METHODS else "OTHER"
        status = response.status_code
        metrics.observe(method, route, str(status), duration)
        if request.path not in SKIP_PATHS:
            level = logging.ERROR if status >= 500 else logging.INFO
            fields = {
                "method": method,
                "route": route,
                "status": status,
                "duration_ms": round(duration * 1000, 2),
            }
            logger.log(level, "request", extra={"fields": fields})
        return response

    @app.get("/metrics")
    def metrics_endpoint():
        return Response(
            metrics.render(version),
            mimetype="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/api/work")
    def api_work():
        # ?delay_ms=300 — повільна відповідь для перевірки p95 на дашборді
        delay_ms = min(max(request.args.get("delay_ms", 0, type=int), 0), 2000)
        if delay_ms:
            time.sleep(delay_ms / 1000)
        return jsonify(ok=True, version=version, delay_ms=delay_ms)

    @app.get("/api/fail")
    def api_fail():
        # завжди 500 — для перевірки фільтра 5xx у Loki
        return jsonify(error="intentional error"), 500

    return metrics
