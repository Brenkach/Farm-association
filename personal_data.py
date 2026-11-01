"""Right of Access / Personal Data Export (Lab 4, Завдання 2).

GET /api/users/<login>/personal-data
Доступ: сам суб'єкт або роль із явним повноваженням (PRIVILEGED_ROLES).
Підключення: register_export_routes(app) в create_app().
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from flask import current_app, jsonify, session

from consent import (
    CONSENT_PURPOSES, ConsentHistory, MarketingOutbox, UserConsent,
    _consent_dict, _iso, api_login_required,
)
from extensions import db
from models import Employee, User

log = logging.getLogger("personal_data")

SCHEMA_VERSION = "1.0"
CATEGORIES = ["profile", "farm_contact", "employee_records", "settings", "activity", "consents"]
PRIVILEGED_ROLES = ("superuser",)

# Мінімізація: ці категорії НІКОЛИ не потрапляють в експорт (назви без самих секретів).
EXCLUDED_FIELDS = [
    "authentication_credentials",
    "session_data",
    "internal_security_flags",
    "data_of_other_users",
]


def subject_ref(login: str) -> str:
    """Безпечний псевдонім для логів: HMAC від логіна, зворотно не відновлюється."""
    key = current_app.config["SECRET_KEY"]
    key = key.encode() if isinstance(key, str) else key
    return "ref_" + hmac.new(key, str(login).encode(), hashlib.sha256).hexdigest()[:12]


def build_personal_data(subject: User, actor_login: str) -> dict:
    """Збирає всі секції. Кожна секція присутня завжди (порожня структура, якщо даних немає)."""
    login = subject.login
    farm = subject.farm

    profile = {
        "login": login,
        "access_right": subject.access_right,
        "farm_id": subject.farm_id,
        "farm_name": farm.name if farm else None,
    }

    # Дані господарства є персональними лише для фермера (він сам їх вказав при реєстрації).
    # Працівникам і суперкористувачу вони не віддаються: це дані іншої особи.
    farm_contact = {}
    if subject.access_right == "farmer" and farm is not None:
        farm_contact = {
            "farmer_fullname": farm.farmer_fullname,
            "region": farm.region,
            "address": farm.address,
            "phone": farm.phone,
        }

    employee_records = [
        {
            "employee_id": e.employee_id,
            "farm_id": e.farm_id,
            "full_name": e.full_name,
            "position": e.position,
            "hire_date": _iso(e.hire_date),
            "monthly_salary": e.monthly_salary,
            "address": e.address,
            "phone": e.phone,
        }
        for e in Employee.query.filter_by(user_login=login).order_by(Employee.employee_id)
    ]

    recs = {r.purpose: r for r in UserConsent.query.filter_by(user_login=login)}
    consents = {
        "current": [_consent_dict(recs.get(p), p) for p in CONSENT_PURPOSES],
        "history": [
            {"purpose": h.purpose, "action": h.action, "policy_version": h.policy_version,
             "source": h.source, "occurred_at": _iso(h.occurred_at)}
            for h in ConsentHistory.query.filter_by(user_login=login).order_by(ConsentHistory.id)
        ],
    }

    activity = {
        "marketing_messages": [
            {"id": m.id, "message": m.message, "created_at": _iso(m.created_at)}
            for m in MarketingOutbox.query.filter_by(user_login=login).order_by(MarketingOutbox.id)
        ]
    }

    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timezone": "UTC",
            "subject_id": login,
            "requested_by": actor_login,
            "categories": CATEGORIES,
            "excluded_fields": EXCLUDED_FIELDS,
        },
        "profile": profile,
        "farm_contact": farm_contact,
        "employee_records": employee_records,
        "settings": {"data": {}, "note": "У системі не зберігаються налаштування профілю."},
        "activity": activity,
        "consents": consents,
    }


def _json(payload: dict, status: int):
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store"
    return resp


@dataclass(frozen=True)
class ExportRequest:
    """Value Object запиту на експорт: хто просить (actor) і чиї дані (subject_login).

    Незмінний (frozen): поля не можна перезаписати після створення. Правила доступу
    живуть усередині об'єкта, а не розкидані змінними в обробнику.
    """

    actor: User
    subject_login: str

    @classmethod
    def for_current_user(cls, subject_login: str) -> "ExportRequest":
        return cls(actor=db.session.get(User, session["login"]), subject_login=subject_login)

    @property
    def is_self(self) -> bool:
        return self.actor.login == self.subject_login

    @property
    def is_privileged(self) -> bool:
        return self.actor.access_right in PRIVILEGED_ROLES

    @property
    def allowed(self) -> bool:
        return self.is_self or self.is_privileged

    def find_subject(self):
        return self.actor if self.is_self else db.session.get(User, self.subject_login)


def _deny(req: ExportRequest):
    # Однакова відповідь для чужого і для неіснуючого профілю: факт існування не розкривається.
    log.info("personal_data_export actor=%s subject=%s result=DENY",
             subject_ref(req.actor.login), subject_ref(req.subject_login))
    return _json({"error": "FORBIDDEN"}, 403)


def _not_found(req: ExportRequest):
    log.info("personal_data_export actor=%s subject=%s result=NOT_FOUND",
             subject_ref(req.actor.login), subject_ref(req.subject_login))
    return _json({"error": "NOT_FOUND"}, 404)


def _ok(req: ExportRequest, subject: User):
    payload = build_personal_data(subject, req.actor.login)
    log.info("personal_data_export actor=%s subject=%s result=OK",
             subject_ref(req.actor.login), subject_ref(subject.login))
    return _json(payload, 200)


def register_export_routes(app):
    @app.get("/api/users/<login>/personal-data")
    @api_login_required
    def api_personal_data(login):
        req = ExportRequest.for_current_user(login)
        if not req.allowed:
            return _deny(req)
        subject = req.find_subject()
        if subject is None:
            return _not_found(req)
        return _ok(req, subject)
