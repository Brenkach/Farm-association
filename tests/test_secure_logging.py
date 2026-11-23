"""Lab 4, Завдання 1: тести безпечного логування. Усі дані синтетичні."""
import io
import json
import logging
from dataclasses import dataclass

import pytest

from privacy_logging import (
    CorrelationIdFilter,
    JsonFormatter,
    PrivacyFilter,
    TEXT_FORMAT,
    install_privacy_filter,
    setup_privacy_logging,
)

EMAIL = "ivan.petrenko@example.com"
PHONE = "+380 50 123 45 67"
LOGIN = "ivan_farmer_test"
PASSWORD = "S3cr3t-P@ss-TEST"
TOKEN = "tok_TEST_abc123XYZ"
API_KEY = "ak_TEST_9f8e7d6c"
SENSITIVE = [EMAIL, "ivan.petrenko", PHONE, "380 50 123", PASSWORD, TOKEN, API_KEY]


def assert_no_leak(output: str, extra=()):
    leaked = [s for s in (*SENSITIVE, *extra) if s in output]
    assert not leaked, f"У логу знайдено sensitive-значення: {leaked}\n{output}"


def make_logger(name, protected=True, json_logs=False):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter(TEXT_FORMAT))
    handler.addFilter(CorrelationIdFilter())
    if protected:
        handler.addFilter(PrivacyFilter())
    lg = logging.getLogger(f"lab4.{name}")
    lg.handlers = [handler]
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    return lg, stream


# ---------------------------- ПОЗИТИВНІ ----------------------------
def test_plain_text_masks_pii_and_redacts_secrets():
    lg, out = make_logger("plain")
    lg.info(
        "op=REGISTER email=%s phone=%s password=%s token=%s api_key=%s",
        EMAIL, PHONE, PASSWORD, TOKEN, API_KEY,
    )
    text = out.getvalue()
    assert_no_leak(text)
    assert "i***@example.com" in text      # діагностична цінність: домен видно
    assert "** 67" in text                 # останні цифри телефону
    assert text.count("[REDACTED]") == 3   # password, token, api_key
    assert "op=REGISTER" in text           # тип операції не втрачено


def test_json_log_stays_valid_and_keeps_diagnostics():
    lg, out = make_logger("json", json_logs=True)
    lg.info(
        "Export requested",
        extra={
            "operation": "EXPORT",
            "correlation_id": "corr-123",
            "payload": {"email": EMAIL, "profile": {"phone": PHONE, "password": PASSWORD}},
        },
    )
    line = out.getvalue().strip()
    assert_no_leak(line)
    data = json.loads(line)                          # формат не зруйновано
    assert data["correlation_id"] == "corr-123"      # correlation ID збережено
    assert data["operation"] == "EXPORT"
    assert data["payload"]["email"] == "i***@example.com"
    assert data["payload"]["profile"]["password"] == "[REDACTED]"


def test_json_embedded_in_text_message():
    lg, out = make_logger("jsontext")
    lg.info("body=%s", json.dumps({"email": EMAIL, "password": PASSWORD, "ok": True}))
    text = out.getvalue()
    assert_no_leak(text)
    assert '"ok": true' in text


def test_diagnostic_numbers_are_not_destroyed():
    lg, out = make_logger("diag")
    lg.info("order_id=1234 corr=123e4567-e89b-12d3-a456-426614174000 at 2026-10-11 16:25:17")
    text = out.getvalue()
    assert "123e4567-e89b-12d3-a456-426614174000" in text
    assert "2026-10-11 16:25:17" in text


def test_login_in_url_path_is_masked():
    lg, out = make_logger("url")
    lg.info('GET /api/users/%s/personal-data 200', LOGIN)
    assert LOGIN not in out.getvalue()


def test_filter_is_idempotent_across_handlers():
    lg, out = make_logger("idem")
    lg.handlers[0].addFilter(PrivacyFilter())  # другий прохід
    lg.info("password=%s email=%s", PASSWORD, EMAIL)
    text = out.getvalue()
    assert_no_leak(text)
    assert "[REDACTED]]" not in text


def test_install_privacy_filter_covers_existing_handlers_once():
    lg, out = make_logger("install", protected=False)
    install_privacy_filter(lg)
    install_privacy_filter(lg)
    assert sum(isinstance(f, PrivacyFilter) for f in lg.handlers[0].filters) == 1
    lg.info("email=%s", EMAIL)
    assert_no_leak(out.getvalue())


def test_setup_privacy_logging_protects_root_handlers():
    root = logging.getLogger()
    old_level, stream = root.level, io.StringIO()
    handler = logging.StreamHandler(stream)
    root.addHandler(handler)
    try:
        setup_privacy_logging()
        logging.getLogger("lab4.wired").info("email=%s token=%s", EMAIL, TOKEN)
        assert_no_leak(stream.getvalue())
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


# ---------------------------- НЕГАТИВНІ ----------------------------
def test_exception_message_and_traceback_are_sanitized():
    lg, out = make_logger("exc")
    try:
        raise ValueError(f"Cannot notify {EMAIL} ({PHONE}); token={TOKEN}")
    except ValueError:
        lg.exception("Notification failed")
    text = out.getvalue()
    assert_no_leak(text)
    assert "Traceback" in text and "ValueError" in text  # технічні дані лишились


@dataclass
class ContactDTO:
    phone: str
    email: str


@dataclass
class UserDTO:
    login: str
    password: str
    contact: ContactDTO


def _dto():
    return UserDTO(LOGIN, PASSWORD, ContactDTO(PHONE, EMAIL))


def test_nested_dto_in_message_repr():
    lg, out = make_logger("dto_repr")
    lg.info("Created user %s", _dto())
    assert_no_leak(out.getvalue(), extra=[LOGIN])


def test_nested_dto_in_extra_structured():
    lg, out = make_logger("dto_extra", json_logs=True)
    lg.info("Created user", extra={"dto": _dto(), "ctx": [{"deep": {"api_key": API_KEY}}]})
    line = out.getvalue()
    assert_no_leak(line, extra=[LOGIN])
    data = json.loads(line)
    assert data["dto"]["password"] == "[REDACTED]"
    assert data["dto"]["contact"]["email"] == "i***@example.com"


def test_leak_detector_fails_on_unprotected_logger():
    """Контроль самого тесту: без фільтра витік ЗНАХОДИТЬСЯ, тест падає."""
    lg, out = make_logger("unprotected", protected=False)
    lg.info("email=%s password=%s", EMAIL, PASSWORD)
    with pytest.raises(AssertionError):
        assert_no_leak(out.getvalue())


# ---------------------------- FLASK ----------------------------
def test_flask_request_logs_are_sanitized_with_correlation_id():
    flask = pytest.importorskip("flask")
    root, stream = logging.getLogger(), io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(correlation_id)s | %(message)s"))
    old_level = root.level
    root.addHandler(handler)
    try:
        app = flask.Flask(__name__)
        setup_privacy_logging(app)

        @app.get("/ping")
        def ping():
            app.logger.info("email=%s password=%s", EMAIL, PASSWORD)
            return "ok"

        resp = app.test_client().get("/ping", headers={"X-Correlation-ID": "abc-123"})
        assert resp.headers["X-Correlation-ID"] == "abc-123"
        text = stream.getvalue()
        assert_no_leak(text)
        assert "abc-123 |" in text
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
