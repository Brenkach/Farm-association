"""Consent Management Engine (Lab 4, Завдання 4).

Містить: моделі (UserConsent, ConsentHistory, MarketingOutbox), ConsentService
(GRANT/REVOKE), ConsentPolicyGate (перевірка перед дією) та API-роути.
Підключення: register_consent_routes(app) в create_app().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps

from flask import jsonify, request, session
from sqlalchemy import UniqueConstraint

from extensions import db
from models import User

log = logging.getLogger("consent")

# Окрема згода на кожну мету. Системні/договірні функції сюди НЕ входять.
CONSENT_PURPOSES = ("MARKETING_EMAIL", "OPTIONAL_ANALYTICS")
CURRENT_POLICY_VERSION = "2026-10-v1"
ALLOWED_SOURCES = ("web_ui", "api", "settings")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC


# --------------------------------------------------------------------------
# Моделі
# --------------------------------------------------------------------------
class UserConsent(db.Model):
    """Поточний стан згоди: один рядок на (користувач, мета)."""

    __tablename__ = "user_consents"
    __table_args__ = (UniqueConstraint("user_login", "purpose", name="uq_consent_user_purpose"),)

    id = db.Column(db.Integer, primary_key=True)
    user_login = db.Column(db.String(50), db.ForeignKey("users.login"), nullable=False, index=True)
    purpose = db.Column(db.String(50), nullable=False)
    is_granted = db.Column(db.Boolean, nullable=False, default=False)
    policy_version = db.Column(db.String(30))
    granted_at = db.Column(db.DateTime)
    withdrawn_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, nullable=False, default=_now)
    source = db.Column(db.String(30))


class ConsentHistory(db.Model):
    """Append-only журнал змін: доказ того, що, коли і як прийняв користувач."""

    __tablename__ = "consent_history"

    id = db.Column(db.Integer, primary_key=True)
    user_login = db.Column(db.String(50), nullable=False, index=True)  # без FK: журнал не видаляється
    purpose = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(10), nullable=False)  # GRANT / REVOKE
    policy_version = db.Column(db.String(30))
    source = db.Column(db.String(30))
    occurred_at = db.Column(db.DateTime, nullable=False, default=_now)


class MarketingOutbox(db.Model):
    """Побічний ефект залежної дії: факт «відправленого» маркетингового повідомлення."""

    __tablename__ = "marketing_outbox"

    id = db.Column(db.Integer, primary_key=True)
    user_login = db.Column(db.String(50), db.ForeignKey("users.login"), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_now)


# --------------------------------------------------------------------------
# Сервіс GRANT / REVOKE (ідемпотентний)
# --------------------------------------------------------------------------
class ConsentService:
    @staticmethod
    def get(login: str, purpose: str):
        # populate_existing: завжди актуальний стан з БД, без застарілого кешу сесії
        return (
            UserConsent.query.populate_existing()
            .filter_by(user_login=login, purpose=purpose)
            .first()
        )

    @classmethod
    def grant(cls, login, purpose, source="api", policy_version=CURRENT_POLICY_VERSION) -> bool:
        """Повертає True, якщо стан змінився; повторний GRANT нічого не пише."""
        rec = cls.get(login, purpose)
        if rec and rec.is_granted and rec.policy_version == policy_version:
            return False
        now = _now()
        try:
            if rec is None:
                rec = UserConsent(user_login=login, purpose=purpose)
                db.session.add(rec)
            rec.is_granted = True
            rec.policy_version = policy_version
            rec.granted_at = now
            rec.withdrawn_at = None
            rec.updated_at = now
            rec.source = source
            db.session.add(ConsentHistory(
                user_login=login, purpose=purpose, action="GRANT",
                policy_version=policy_version, source=source, occurred_at=now))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return True

    @classmethod
    def revoke(cls, login, purpose, source="api") -> bool:
        """Повертає True, якщо стан змінився; REVOKE без активної згоди нічого не пише."""
        rec = cls.get(login, purpose)
        if rec is None or not rec.is_granted:
            return False
        now = _now()
        try:
            rec.is_granted = False
            rec.withdrawn_at = now
            rec.updated_at = now
            rec.source = source
            db.session.add(ConsentHistory(
                user_login=login, purpose=purpose, action="REVOKE",
                policy_version=rec.policy_version, source=source, occurred_at=now))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return True


# --------------------------------------------------------------------------
# Policy Gate
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


class ConsentDenied(Exception):
    def __init__(self, decision: Decision):
        super().__init__(decision.reason)
        self.decision = decision


class ConsentPolicyGate:
    """Перевіряє АКТУАЛЬНУ згоду в БД безпосередньо перед дією (без кешу)."""

    def check(self, login: str, purpose: str) -> Decision:
        if purpose not in CONSENT_PURPOSES:
            return Decision(False, "UNKNOWN_PURPOSE")
        rec = ConsentService.get(login, purpose)
        if rec is None:
            return Decision(False, "NO_RECORD")
        if not rec.is_granted:
            return Decision(False, "WITHDRAWN")
        if rec.policy_version != CURRENT_POLICY_VERSION:
            return Decision(False, "POLICY_VERSION_MISMATCH")
        return Decision(True, "GRANTED")

    def require(self, login: str, purpose: str) -> None:
        decision = self.check(login, purpose)
        if not decision.allowed:
            raise ConsentDenied(decision)


def send_marketing_message(login: str, text: str) -> int:
    """Залежна дія. Gate викликається ТУТ, тож background job теж перевіряє актуальну згоду."""
    ConsentPolicyGate().require(login, "MARKETING_EMAIL")
    msg = MarketingOutbox(user_login=login, message=text)
    db.session.add(msg)
    db.session.commit()
    return msg.id


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def api_login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        login = session.get("login")
        if not login or db.session.get(User, login) is None:
            session.clear()
            return jsonify(error="UNAUTHENTICATED"), 401
        return fn(*args, **kwargs)

    return wrapper


def _iso(dt):
    return dt.isoformat() if dt else None


def _consent_dict(rec, purpose):
    return {
        "purpose": purpose,
        "is_granted": bool(rec and rec.is_granted),
        "policy_version": rec.policy_version if rec else None,
        "granted_at": _iso(rec.granted_at) if rec else None,
        "withdrawn_at": _iso(rec.withdrawn_at) if rec else None,
        "updated_at": _iso(rec.updated_at) if rec else None,
        "source": rec.source if rec else None,
    }


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def register_consent_routes(app):
    # Усі операції діють лише на користувача з сесії: у URL немає user id, тож немає IDOR.

    @app.get("/api/consents")
    @api_login_required
    def api_consents_list():
        recs = UserConsent.query.filter_by(user_login=session["login"]).all()
        by_purpose = {r.purpose: r for r in recs}
        return jsonify(
            current_policy_version=CURRENT_POLICY_VERSION,
            consents=[_consent_dict(by_purpose.get(p), p) for p in CONSENT_PURPOSES],
        )

    @app.get("/api/consents/history")
    @api_login_required
    def api_consents_history():
        rows = (ConsentHistory.query.filter_by(user_login=session["login"])
                .order_by(ConsentHistory.id).all())
        return jsonify(history=[
            {"purpose": r.purpose, "action": r.action, "policy_version": r.policy_version,
             "source": r.source, "occurred_at": _iso(r.occurred_at)} for r in rows])

    @app.post("/api/consents/<purpose>/grant")
    @api_login_required
    def api_consent_grant(purpose):
        if purpose not in CONSENT_PURPOSES:
            return jsonify(error="UNKNOWN_PURPOSE"), 400
        data = _json_body()
        version = data.get("policy_version", CURRENT_POLICY_VERSION)
        source = data.get("source", "api")
        if source not in ALLOWED_SOURCES:
            return jsonify(error="INVALID_SOURCE"), 400
        if version != CURRENT_POLICY_VERSION:
            return jsonify(error="POLICY_VERSION_MISMATCH",
                           current_policy_version=CURRENT_POLICY_VERSION), 409
        changed = ConsentService.grant(session["login"], purpose, source, version)
        log.info("consent op=GRANT purpose=%s login=%s changed=%s",
                 purpose, session["login"], changed)
        return jsonify(purpose=purpose, is_granted=True, changed=changed)

    @app.post("/api/consents/<purpose>/revoke")
    @api_login_required
    def api_consent_revoke(purpose):
        if purpose not in CONSENT_PURPOSES:
            return jsonify(error="UNKNOWN_PURPOSE"), 400
        source = _json_body().get("source", "api")
        if source not in ALLOWED_SOURCES:
            return jsonify(error="INVALID_SOURCE"), 400
        changed = ConsentService.revoke(session["login"], purpose, source)
        log.info("consent op=REVOKE purpose=%s login=%s changed=%s",
                 purpose, session["login"], changed)
        return jsonify(purpose=purpose, is_granted=False, changed=changed)

    @app.post("/api/marketing/send-test")
    @api_login_required
    def api_marketing_send_test():
        login = session["login"]
        text = str(_json_body().get("message", "Test marketing message"))[:200]
        try:
            outbox_id = send_marketing_message(login, text)
        except ConsentDenied as e:
            log.info("marketing_send login=%s result=DENY reason=%s", login, e.decision.reason)
            return jsonify(status="DENIED", reason=e.decision.reason), 403
        log.info("marketing_send login=%s result=ALLOW outbox_id=%s", login, outbox_id)
        return jsonify(status="SENT", outbox_id=outbox_id)
