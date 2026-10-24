"""Централізоване безпечне логування (Lab 4, Завдання 1).

Єдина точка санітизації для всіх логів застосунку:
  * PrivacyFilter  - вішається на handler'и, обробляє текст, args, extra, exception;
  * JsonFormatter  - структурований JSON-лог (додатково санітизує payload);
  * setup_privacy_logging(app) - підключення в create_app().

Політика:
  email / phone / login / ПІБ / адреса -> часткове маскування
  password, token, api key, secret, authorization -> [REDACTED]
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

REDACTED = "[REDACTED]"
_MAX_DEPTH = 8


# --------------------------------------------------------------------------
# Функції маскування
# --------------------------------------------------------------------------
def mask_generic(value: Any) -> str:
    s = str(value)
    if s.endswith("***"):  # вже замасковано (ідемпотентність)
        return s
    return "***" if len(s) <= 2 else f"{s[0]}***"


def mask_email(value: str) -> str:
    local, sep, domain = value.partition("@")
    if not sep:
        return mask_generic(value)
    return f"{local[:1]}***@{domain}"


def mask_phone(value: str) -> str:
    """Залишає лише останні 2 цифри, зберігає формат (+, пробіли, дужки)."""
    total = sum(c.isdigit() for c in value)
    seen, out = 0, []
    for c in value:
        if c.isdigit():
            seen += 1
            out.append(c if seen > total - 2 else "*")
        else:
            out.append(c)
    return "".join(out)


# --------------------------------------------------------------------------
# Політика за іменами полів (для dict / DTO / extra)
# --------------------------------------------------------------------------
_SECRET_KEY_RE = re.compile(
    r"password|passwd|pwd|token|secret|api[_-]?key|authorization|cookie|credential",
    re.I,
)
_MASKED_KEYS: dict[str, Callable[[str], str]] = {
    "email": mask_email,
    "e_mail": mask_email,
    "phone": mask_phone,
    "phone_number": mask_phone,
    "mobile": mask_phone,
    "tel": mask_phone,
    "login": mask_generic,
    "user_login": mask_generic,
    "username": mask_generic,
    "full_name": mask_generic,
    "farmer_fullname": mask_generic,
    "address": mask_generic,
}

# --------------------------------------------------------------------------
# Політика для вільного тексту (рядки логу, exception, repr об'єктів)
# --------------------------------------------------------------------------
_VAL = r"(?P<val>\[REDACTED\]|\"[^\"]*\"|'[^']*'|[^\s,;&})\]]+)"
_JWT_RE = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*")
_BEARER_RE = re.compile(r"\b(Bearer|Basic)\s+[\w.~+/=-]+", re.I)
_SECRET_NAME = (
    r"[\w.-]*(?:password|passwd|pwd|token|secret|api[_-]?key|authorization)[\w.-]*"
)
_KV_SECRET_RE = re.compile(
    r"(?P<key>[\"']?" + _SECRET_NAME + r"[\"']?\s*[=:]\s*)" + _VAL, re.I
)
_MASK_NAMES = [k for k, f in _MASKED_KEYS.items() if f is mask_generic]
_KV_MASK_RE = re.compile(
    r"(?P<key>[\"']?\b(?:" + "|".join(_MASK_NAMES) + r")[\"']?\s*[=:]\s*)" + _VAL, re.I
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"(?<![\w.-])\+?\d[\d ()-]{7,}\d(?!\w)")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_USER_PATH_RE = re.compile(r"(/api/users/)([^/\s?\"']+)")  # login в URL (access log)


def _sub_kv(redact: bool):
    def repl(m: re.Match) -> str:
        val, key = m.group("val"), m.group("key")
        if val == REDACTED:
            return m.group(0)
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            q, inner = val[0], val[1:-1]
            return f"{key}{q}{REDACTED if redact else mask_generic(inner)}{q}"
        return f"{key}{REDACTED if redact else mask_generic(val)}"

    return repl


def _sub_phone(m: re.Match) -> str:
    s = m.group(0)
    digits = sum(c.isdigit() for c in s)
    if not 9 <= digits <= 15 or _DATE_RE.match(s):
        return s  # не схоже на телефон (дата, довгий ID) - не ламаємо діагностику
    return mask_phone(s)


def sanitize_text(text: str) -> str:
    text = _JWT_RE.sub(REDACTED, text)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _KV_SECRET_RE.sub(_sub_kv(True), text)
    text = _KV_MASK_RE.sub(_sub_kv(False), text)
    text = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), text)
    text = _PHONE_RE.sub(_sub_phone, text)
    text = _USER_PATH_RE.sub(lambda m: m.group(1) + mask_generic(m.group(2)), text)
    return text


# --------------------------------------------------------------------------
# Санітизація структур (dict, list, dataclass/DTO, довільні об'єкти)
# --------------------------------------------------------------------------
def sanitize(value: Any, key: Any = None, _depth: int = 0) -> Any:
    if key is not None:
        if _SECRET_KEY_RE.search(str(key)):
            return REDACTED
        masker = _MASKED_KEYS.get(str(key).lower())
        if masker is not None:
            if value is None:
                return None
            return masker(value) if isinstance(value, str) else REDACTED
    if _depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, (bytes, bytearray)):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): sanitize(v, k, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize(v, None, _depth + 1) for v in value]
    if isinstance(value, BaseException):
        return sanitize_text(f"{type(value).__name__}: {value}")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            return sanitize(dataclasses.asdict(value), None, _depth + 1)
        except Exception:
            return sanitize_text(repr(value))
    if hasattr(value, "__dict__"):
        public = {k: v for k, v in vars(value).items() if not k.startswith("_")}
        return sanitize(public, None, _depth + 1)
    return sanitize_text(str(value))


# --------------------------------------------------------------------------
# logging інтеграція
# --------------------------------------------------------------------------
_STD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


class PrivacyFilter(logging.Filter):
    """Санітизує запис ДО форматування, тому працює з будь-яким Formatter."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "_privacy_done", False):
            return True
        try:
            message = record.getMessage()
        except Exception:
            message = f"{record.msg!s} {record.args!s}"
        record.msg = sanitize_text(message)
        record.args = ()

        for k, v in list(record.__dict__.items()):  # extra={...}
            if k in _STD_ATTRS or k.startswith("_"):
                continue
            record.__dict__[k] = sanitize(v, k)

        if record.exc_info:  # exception message + traceback
            text = "".join(traceback.format_exception(*record.exc_info)).rstrip()
            record.exc_text = sanitize_text(text)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = sanitize_text(record.exc_text)
        if record.stack_info:
            record.stack_info = sanitize_text(record.stack_info)

        record._privacy_done = True
        return True


_CID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


class CorrelationIdFilter(logging.Filter):
    """Додає record.correlation_id (зі Flask g, інакше '-')."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            cid = "-"
            try:
                from flask import g, has_request_context

                if has_request_context():
                    cid = getattr(g, "correlation_id", "-")
            except ImportError:
                pass
            record.correlation_id = cid
        return True


class JsonFormatter(logging.Formatter):
    """JSON-лог. Додатково санітизує payload (defence in depth)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        for k, v in record.__dict__.items():
            if k not in _STD_ATTRS and not k.startswith("_") and k not in payload:
                payload[k] = v
        if record.exc_text:
            payload["exception"] = record.exc_text
        elif record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        payload = sanitize(payload)
        ts = datetime.fromtimestamp(record.created, timezone.utc).isoformat(
            timespec="milliseconds"
        )
        return json.dumps({"ts": ts, **payload}, ensure_ascii=False, default=str)


TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(correlation_id)s] %(message)s"


def install_privacy_filter(*loggers: logging.Logger) -> None:
    """Додає фільтри до ВСІХ handler'ів переданих логерів (ідемпотентно)."""
    for lg in loggers:
        for h in lg.handlers:
            if not any(isinstance(f, CorrelationIdFilter) for f in h.filters):
                h.addFilter(CorrelationIdFilter())
            if not any(isinstance(f, PrivacyFilter) for f in h.filters):
                h.addFilter(PrivacyFilter())


def init_correlation_id(app) -> None:
    from flask import g, request

    @app.before_request
    def _set_correlation_id():
        raw = request.headers.get("X-Correlation-ID", "")
        g.correlation_id = raw if _CID_RE.fullmatch(raw) else uuid.uuid4().hex

    @app.after_request
    def _echo_correlation_id(response):
        response.headers["X-Correlation-ID"] = getattr(g, "correlation_id", "-")
        return response


def setup_privacy_logging(app=None, level: int = logging.INFO, json_logs: bool = False):
    """Викликати на початку create_app(), ДО першого звернення до app.logger."""
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter(TEXT_FORMAT))
        root.addHandler(handler)
    targets = [root, logging.getLogger("werkzeug")]
    if app is not None:
        targets.append(app.logger)
        init_correlation_id(app)
    install_privacy_filter(*targets)
