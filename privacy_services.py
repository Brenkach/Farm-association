"""Інтерфейсна декомпозиція God Object (Лаб. 8, PASS).

PrivacyGodService розбито на чотири незалежні класи з однією відповідальністю (SRP):
    ConsentManager, MarketingDispatcher, PersonalDataExporter, ErasureService.
Класи не знають один про одного й про конкретні реалізації: вони отримують залежності через
конструктор (Dependency Injection) і розмовляють з оточенням лише через контракти (Protocol):
    AuditSink, Clock, Masker, ConsentChecker.
Єдине місце, що знає про сигнатуру сторонніх класів, це тонкі адаптери (AuditTrailSink тощо).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from anonymization import AnonymizationResult, AuditEvent, ProtectedAccount, UserNotFound
from audit_trail import AuditTrail
from consent import (
    CONSENT_PURPOSES, CURRENT_POLICY_VERSION, ConsentDenied, ConsentHistory, ConsentPolicyGate,
    Decision, MarketingOutbox, UserConsent, _now,
)
from extensions import db
from models import Employee, Farm, User
from personal_data import ExportRequest, subject_ref
from privacy_logging import sanitize_text

MARKETING_PURPOSE = "MARKETING_EMAIL"
MAX_MESSAGE_LEN = 200


# =========================================================================== контракти (інтерфейси)
class AuditSink(Protocol):
    def record(self, subject: str, event_type: str, result: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class Masker(Protocol):
    def mask(self, text: str) -> str: ...


class ConsentChecker(Protocol):
    def check(self, login: str, purpose: str) -> Decision: ...


# =========================================================================== Value Object
@dataclass(frozen=True)
class ConsentPolicy:
    """Незмінна політика згод: дозволені мети та поточна версія тексту політики."""

    purposes: tuple = CONSENT_PURPOSES
    version: str = CURRENT_POLICY_VERSION


# =========================================================================== адаптери до сторонніх класів
class SystemClock:
    def now(self) -> datetime:
        return _now()


class SanitizeMasker:
    def mask(self, text: str) -> str:
        return sanitize_text(text)


class GateConsentChecker:
    """Адаптер до ConsentPolicyGate: перевіряє актуальну згоду в БД."""

    def __init__(self, gate: ConsentPolicyGate | None = None):
        self._gate = gate or ConsentPolicyGate()

    def check(self, login: str, purpose: str) -> Decision:
        return self._gate.check(login, purpose)

    def status(self, login: str, purpose: str) -> dict:
        decision = self._gate.check(login, purpose)
        return {"purpose": purpose, "granted": decision.allowed, "reason": decision.reason}


class AuditTrailSink:
    """Адаптер журналу аудиту: єдине місце, що знає сигнатуру AuditTrail.record()."""

    def __init__(self, trail: AuditTrail | None = None, actor: str = "SYSTEM"):
        self._trail = trail or AuditTrail()
        self._actor = actor

    def record(self, subject: str, event_type: str, result: str) -> None:
        self._trail.record(subject, event_type, result, actor=self._actor)


def recent_audit(limit: int = 10) -> list:
    events = AuditEvent.query.order_by(AuditEvent.id.desc()).limit(limit).all()
    return [{"event": e.event_type, "result": e.result} for e in events]


# =========================================================================== 1. згоди
class ConsentManager:
    """Життєвий цикл згод: GRANT та REVOKE з журналом історії та аудитом."""

    def __init__(self, policy: ConsentPolicy, clock: Clock, audit: AuditSink):
        self._policy = policy
        self._clock = clock
        self._audit = audit

    def grant(self, login: str, purpose: str, source: str = "api") -> bool:
        if purpose not in self._policy.purposes:
            raise ValueError(f"unknown purpose: {purpose}")
        rec = UserConsent.query.filter_by(user_login=login, purpose=purpose).first()
        if rec and rec.is_granted and rec.policy_version == self._policy.version:
            return False
        now = self._clock.now()
        if rec is None:
            rec = UserConsent(user_login=login, purpose=purpose)
            db.session.add(rec)
        rec.is_granted, rec.policy_version, rec.granted_at = True, self._policy.version, now
        rec.withdrawn_at, rec.updated_at, rec.source = None, now, source
        db.session.add(ConsentHistory(user_login=login, purpose=purpose, action="GRANT",
                                      policy_version=self._policy.version, source=source, occurred_at=now))
        db.session.commit()
        self._audit.record(login, "CONSENT_GRANT", "OK")
        return True

    def revoke(self, login: str, purpose: str, source: str = "api") -> bool:
        if purpose not in self._policy.purposes:
            raise ValueError(f"unknown purpose: {purpose}")
        rec = UserConsent.query.populate_existing().filter_by(user_login=login, purpose=purpose).first()
        if rec is None or not rec.is_granted:
            return False
        now = self._clock.now()
        rec.is_granted, rec.withdrawn_at, rec.updated_at, rec.source = False, now, now, source
        db.session.add(ConsentHistory(user_login=login, purpose=purpose, action="REVOKE",
                                      policy_version=rec.policy_version, source=source, occurred_at=now))
        db.session.commit()
        self._audit.record(login, "CONSENT_REVOKE", "OK")
        return True


# =========================================================================== 2. маркетинг
class MarketingDispatcher:
    """Залежна дія: надсилає маркетинг лише за актуальної згоди."""

    def __init__(self, consents: ConsentChecker, audit: AuditSink):
        self._consents = consents
        self._audit = audit

    def send(self, login: str, text: str) -> int:
        decision = self._consents.check(login, MARKETING_PURPOSE)
        if not decision.allowed:
            self._audit.record(login, "MARKETING_SEND", "DENIED")
            raise ConsentDenied(decision)
        msg = MarketingOutbox(user_login=login, message=text[:MAX_MESSAGE_LEN])
        db.session.add(msg)
        db.session.commit()
        self._audit.record(login, "MARKETING_SEND", "OK")
        return msg.id

    def broadcast(self, logins: list, text: str) -> int:
        sent = [self.send(login, text) for login in logins if self._consents.check(login, MARKETING_PURPOSE).allowed]
        self._audit.record("*", "MARKETING_BROADCAST", str(len(sent)))
        return len(sent)


# =========================================================================== 3. експорт даних
class PersonalDataExporter:
    """Право доступу: збирає дані суб'єкта, маскує та пише аудит."""

    def __init__(self, masker: Masker, audit: AuditSink):
        self._masker = masker
        self._audit = audit

    def export(self, actor_login: str, login: str) -> dict:
        request = ExportRequest(actor=db.session.get(User, actor_login), subject_login=login)
        if not request.allowed:
            self._audit.record(login, "DATA_EXPORT", "DENIED")
            raise PermissionError("forbidden")
        subject = request.find_subject()
        if subject is None:
            raise UserNotFound(login)
        employees = Employee.query.filter_by(user_login=login).all()
        farm = db.session.get(Farm, subject.farm_id) if subject.farm_id else None
        data = {"login": self._masker.mask(subject.login), "role": subject.access_right,
                "employees": [self._masker.mask(e.full_name) for e in employees],
                "farm": farm.name if farm else None,
                "consent_events": ConsentHistory.query.filter_by(user_login=login).count()}
        self._audit.record(login, "DATA_EXPORT", "OK")
        return data

    def describe(self, login: str) -> str:
        self._audit.record(login, "DATA_DESCRIBE", "OK")
        return self._masker.mask(f"user={login}")


# =========================================================================== 4. анонімізація
class ErasureService:
    """Право на забуття: анонімізація суб'єкта та «сухий прогін» плану видалення."""

    def __init__(self, audit: AuditSink, protected_roles: tuple = ("superuser",)):
        self._audit = audit
        self._protected_roles = protected_roles

    def anonymize(self, login: str) -> AnonymizationResult:
        user = db.session.get(User, login)
        if user is None:
            raise UserNotFound(login)
        if user.access_right in self._protected_roles:
            raise ProtectedAccount(login)
        if user.access_right == "anonymized":
            return AnonymizationResult("ALREADY_ANONYMIZED", subject_ref(login))
        for emp in Employee.query.filter_by(user_login=login).all():
            emp.full_name, emp.phone, emp.address = "ANONYMIZED", None, None
        for rec in UserConsent.query.filter_by(user_login=login, is_granted=True).all():
            rec.is_granted, rec.withdrawn_at = False, _now()
        MarketingOutbox.query.filter_by(user_login=login).delete()
        user.password_hash, user.access_right = None, "anonymized"
        db.session.commit()
        self._audit.record(login, "ANONYMIZE", "OK")
        return AnonymizationResult("ANONYMIZED", subject_ref(login))

    def plan(self, login: str) -> list:
        user = db.session.get(User, login)
        if user is None:
            raise UserNotFound(login)
        if user.access_right in self._protected_roles:
            raise ProtectedAccount(login)
        checks = {"employees": Employee.query.filter_by(user_login=login).count(),
                  "user_consents": UserConsent.query.filter_by(user_login=login, is_granted=True).count(),
                  "marketing_outbox": MarketingOutbox.query.filter_by(user_login=login).count()}
        entities = ["users"] + [name for name, count in checks.items() if count]
        self._audit.record(login, "ERASURE_PLAN", "OK")
        return entities


# =========================================================================== композиція (точка збирання)
@dataclass(frozen=True)
class PrivacyServices:
    consents: ConsentManager
    marketing: MarketingDispatcher
    exporter: PersonalDataExporter
    erasure: ErasureService


def build_default_services(audit: AuditSink | None = None) -> PrivacyServices:
    """Єдине місце, де конкретні реалізації підключаються до контрактів."""
    sink = audit or AuditTrailSink()
    return PrivacyServices(
        consents=ConsentManager(ConsentPolicy(), SystemClock(), sink),
        marketing=MarketingDispatcher(GateConsentChecker(), sink),
        exporter=PersonalDataExporter(SanitizeMasker(), sink),
        erasure=ErasureService(sink),
    )
