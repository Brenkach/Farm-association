"""Right to Erasure / Anonymization workflow (Lab 4, Завдання 3).

POST /api/users/<login>/anonymize
Доступ: сам суб'єкт або роль з явним повноваженням. Усе виконується в ОДНІЙ транзакції.
Підключення: register_anonymization_routes(app) в create_app().
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from flask import g, has_request_context, jsonify, session

from consent import ConsentHistory, MarketingOutbox, UserConsent, _now, api_login_required
from extensions import db
from models import Employee, User
from personal_data import PRIVILEGED_ROLES, subject_ref

log = logging.getLogger("anonymization")

ANON_PREFIX = "anon-"
ANON_ROLE = "anonymized"
PROTECTED_ROLES = ("superuser",)  # системні акаунти не анонімізуються через API

# Політика обробки сутностей (для звіту; тести перевіряють її відповідність коду).
ERASURE_POLICY = {
    "users": ("ANONYMIZE", "login (PK) -> випадковий anon-<uuid> без збереженого відображення, "
                           "пароль знищується, роль 'anonymized'; рядок лишається заради FK"),
    "employees": ("ANONYMIZE", "ПІБ -> заглушка, адреса і телефон -> NULL, дата найму -> 1 січня; "
                               "посада і зарплата RETAIN (змодельований облік оплати праці)"),
    "farms": ("ANONYMIZE", "farmer_fullname/address/phone очищаються, лише якщо суб'єкт - єдиний "
                           "фермер господарства; назва, регіон, дозволи RETAIN (регуляторні дані)"),
    "user_consents": ("ANONYMIZE", "активні згоди відкликаються, запис переноситься на anon-login"),
    "consent_history": ("ANONYMIZE", "журнал лишається як доказ, але під anon-login"),
    "marketing_outbox": ("DELETE", "маркетингові повідомлення не мають підстави для збереження"),
    "product_offers": ("SKIP", "бізнес-дані господарства, не персональні дані суб'єкта"),
    "audit_events": ("RETAIN", "лише факт операції, час, результат, псевдонім actor, correlation ID; без PII"),
}


class UserNotFound(Exception):
    pass


class ProtectedAccount(Exception):
    pass


@dataclass(frozen=True)
class AnonymizationResult:
    status: str          # ANONYMIZED | ALREADY_ANONYMIZED
    anonymous_id: str


class AuditEvent(db.Model):
    """Privacy-safe audit: без логінів, імен та інших PII."""

    __tablename__ = "audit_events"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(30), nullable=False)
    subject_ref = db.Column(db.String(64))   # anon-login (або NULL при збої)
    actor_ref = db.Column(db.String(64))     # 'SELF' або HMAC-псевдонім адміністратора
    result = db.Column(db.String(20), nullable=False)
    correlation_id = db.Column(db.String(64))
    occurred_at = db.Column(db.DateTime, nullable=False, default=_now)


def _correlation_id() -> str:
    return getattr(g, "correlation_id", "-") if has_request_context() else "-"


def _actor_ref(actor_login: str, subject_login: str) -> str:
    # Для самовидалення НЕ зберігаємо псевдонім старого логіна: це лишило б зв'язок з ним.
    return "SELF" if actor_login == subject_login else subject_ref(actor_login)


# ----------------------------- кроки workflow -----------------------------
def _create_anonymous_user(user: User, new_login: str) -> None:
    db.session.add(User(login=new_login, password_hash=None,
                        access_right=ANON_ROLE, farm_id=user.farm_id))
    db.session.flush()  # новий PK має існувати до перенесення FK


def _anonymize_farm_contact(user: User) -> None:
    farm = user.farm
    if farm is None or user.access_right != "farmer":
        return
    other_farmers = User.query.filter(
        User.farm_id == farm.farm_id, User.access_right == "farmer", User.login != user.login
    ).count()
    if other_farmers:  # дані можуть належати іншій особі
        return
    farm.farmer_fullname = "Anonymized farmer"
    farm.address = None
    farm.phone = None


def _anonymize_employees(old: str, new: str) -> None:
    for e in Employee.query.filter_by(user_login=old).all():
        e.full_name = "Anonymized employee"
        e.address = None
        e.phone = None
        if e.hire_date:
            e.hire_date = date(e.hire_date.year, 1, 1)  # узагальнення проти непрямої ідентифікації
        e.user_login = new


def _withdraw_and_repoint_consents(old: str, new: str) -> None:
    now = _now()
    for rec in UserConsent.query.filter_by(user_login=old).all():
        if rec.is_granted:  # видалення = припинення обробки: активні згоди відкликаються
            rec.is_granted = False
            rec.withdrawn_at = now
            rec.updated_at = now
            rec.source = "erasure"
            db.session.add(ConsentHistory(user_login=old, purpose=rec.purpose, action="REVOKE",
                                          policy_version=rec.policy_version, source="erasure",
                                          occurred_at=now))
        rec.user_login = new
    db.session.flush()
    for h in ConsentHistory.query.filter_by(user_login=old).all():
        h.user_login = new


def _delete_outbox(old: str) -> None:
    MarketingOutbox.query.filter_by(user_login=old).delete(synchronize_session=False)


def _record_failure(actor_login: str, subject_login: str) -> None:
    """Окрема транзакція ПІСЛЯ rollback: факт збою без жодних PII."""
    try:
        db.session.add(AuditEvent(event_type="ERASURE", subject_ref=None,
                                  actor_ref=_actor_ref(actor_login, subject_login),
                                  result="FAILED", correlation_id=_correlation_id()))
        db.session.commit()
    except Exception:
        db.session.rollback()


def anonymize_user(login: str, actor_login: str) -> AnonymizationResult:
    user = db.session.get(User, login)
    if user is None:
        raise UserNotFound()
    if user.access_right == ANON_ROLE:  # ідемпотентність: повторно нічого не змінюємо
        return AnonymizationResult("ALREADY_ANONYMIZED", login)
    if user.access_right in PROTECTED_ROLES:
        raise ProtectedAccount()

    new_login = ANON_PREFIX + uuid.uuid4().hex[:16]
    try:
        _create_anonymous_user(user, new_login)
        _anonymize_farm_contact(user)
        _anonymize_employees(login, new_login)
        _withdraw_and_repoint_consents(login, new_login)
        _delete_outbox(login)
        db.session.flush()  # усі FK перенесено; тепер можна видалити старий PK
        db.session.execute(sa.delete(User).where(User.login == login))
        db.session.add(AuditEvent(event_type="ERASURE", subject_ref=new_login,
                                  actor_ref=_actor_ref(actor_login, login), result="OK",
                                  correlation_id=_correlation_id()))
        db.session.commit()
    except Exception:
        db.session.rollback()  # атомарність: або все, або нічого
        _record_failure(actor_login, login)
        raise
    return AnonymizationResult("ANONYMIZED", new_login)


# --------------------------------- API ---------------------------------
def register_anonymization_routes(app):
    @app.post("/api/users/<login>/anonymize")
    @api_login_required
    def api_anonymize(login):
        actor = db.session.get(User, session["login"])
        is_self = actor.login == login
        if not (is_self or actor.access_right in PRIVILEGED_ROLES):
            log.info("anonymize actor=%s subject=%s result=DENY",
                     subject_ref(actor.login), subject_ref(login))
            return jsonify(error="FORBIDDEN"), 403  # однаково для чужого і неіснуючого

        try:
            result = anonymize_user(login, actor.login)
        except UserNotFound:
            return jsonify(error="NOT_FOUND"), 404
        except ProtectedAccount:
            return jsonify(error="PROTECTED_ACCOUNT"), 409
        except Exception as e:  # деталі помилки можуть містити PII, тому логуємо лише тип
            log.error("anonymize actor=%s result=FAILED error_type=%s",
                      subject_ref(actor.login), type(e).__name__)
            return jsonify(error="ANONYMIZATION_FAILED"), 500

        if is_self:
            session.clear()
        log.info("anonymize actor=%s subject=%s result=%s",
                 "SELF" if is_self else subject_ref(actor.login),
                 result.anonymous_id, result.status)
        return jsonify(status=result.status, anonymous_id=result.anonymous_id)
