"""God Object (Лаб. 8, штучна агрегація): уся логіка приватності в одному класі.

Розпорошена по consent.py, personal_data.py, anonymization.py і privacy_logging.py бізнес-логіка
зібрана в один монолітний клас: згоди, маркетинг, експорт даних, анонімізація, маскування, аудит.
Клас безпосередньо залежить від 16 класів проєкту і майже не має спільного стану між методами.
"""
from __future__ import annotations

from anonymization import AnonymizationResult, AuditEvent, ProtectedAccount, UserNotFound
from audit_trail import AuditTrail
from consent import (
    CONSENT_PURPOSES, CURRENT_POLICY_VERSION, ConsentDenied, ConsentHistory, ConsentPolicyGate,
    ConsentService, Decision, MarketingOutbox, UserConsent, _now,
)
from extensions import db
from models import Employee, Farm, User
from personal_data import ExportRequest, subject_ref
from privacy_logging import sanitize_text


class PrivacyGodService:
    """Бере на себе згоди, маркетинг, експорт, анонімізацію, маскування та аудит одночасно."""

    def __init__(self, clock=_now, policy_version=CURRENT_POLICY_VERSION, purposes=CONSENT_PURPOSES,
                 protected_roles=("superuser",), max_message_len=200, masker=sanitize_text):
        self._clock = clock
        self._policy_version = policy_version
        self._purposes = purposes
        self._protected_roles = protected_roles
        self._max_message_len = max_message_len
        self._masker = masker
        self._audit = AuditTrail()

    # ---- згоди -------------------------------------------------------------------------
    def grant_consent(self, login, purpose, source="api") -> bool:
        if purpose not in self._purposes:
            raise ValueError(f"unknown purpose: {purpose}")
        rec = UserConsent.query.filter_by(user_login=login, purpose=purpose).first()
        if rec and rec.is_granted and rec.policy_version == self._policy_version:
            return False
        now = self._clock()
        if rec is None:
            rec = UserConsent(user_login=login, purpose=purpose)
            db.session.add(rec)
        rec.is_granted, rec.policy_version, rec.granted_at = True, self._policy_version, now
        rec.withdrawn_at, rec.updated_at, rec.source = None, now, source
        db.session.add(ConsentHistory(user_login=login, purpose=purpose, action="GRANT",
                                      policy_version=self._policy_version, source=source, occurred_at=now))
        db.session.commit()
        self._audit.record(login, "CONSENT_GRANT", "OK")
        return True

    def revoke_consent(self, login, purpose, source="api") -> bool:
        rec = ConsentService.get(login, purpose)
        if rec is None or not rec.is_granted:
            return False
        now = self._clock()
        rec.is_granted, rec.withdrawn_at, rec.updated_at, rec.source = False, now, now, source
        db.session.add(ConsentHistory(user_login=login, purpose=purpose, action="REVOKE",
                                      policy_version=rec.policy_version, source=source, occurred_at=now))
        db.session.commit()
        self._audit.record(login, "CONSENT_REVOKE", "OK")
        return True

    def consent_status(self, login, purpose) -> dict:
        decision: Decision = ConsentPolicyGate().check(login, purpose)
        return {"purpose": purpose, "granted": decision.allowed, "reason": decision.reason}

    # ---- маркетинг ---------------------------------------------------------------------
    def send_marketing(self, login, text) -> int:
        decision = ConsentPolicyGate().check(login, "MARKETING_EMAIL")
        if not decision.allowed:
            self._audit.record(login, "MARKETING_SEND", "DENIED")
            raise ConsentDenied(decision)
        msg = MarketingOutbox(user_login=login, message=text[: self._max_message_len], created_at=self._clock())
        db.session.add(msg)
        db.session.commit()
        self._audit.record(login, "MARKETING_SEND", "OK")
        return msg.id

    # ---- експорт персональних даних ------------------------------------------------------
    def export_personal_data(self, actor_login, login) -> dict:
        request = ExportRequest(actor=db.session.get(User, actor_login), subject_login=login)
        if not request.allowed:
            self._audit.record(login, "DATA_EXPORT", "DENIED")
            raise PermissionError("forbidden")
        subject = request.find_subject()
        if subject is None:
            raise UserNotFound(login)
        employees = Employee.query.filter_by(user_login=login).all()
        farm = db.session.get(Farm, subject.farm_id) if subject.farm_id else None
        data = {"login": self._masker(subject.login), "role": subject.access_right,
                "employees": [self._masker(e.full_name) for e in employees],
                "farm": farm.name if farm else None,
                "consent_events": ConsentHistory.query.filter_by(user_login=login).count()}
        self._audit.record(login, "DATA_EXPORT", "OK")
        return data

    # ---- анонімізація --------------------------------------------------------------------
    def anonymize_user(self, login) -> AnonymizationResult:
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
            rec.is_granted, rec.withdrawn_at = False, self._clock()
        MarketingOutbox.query.filter_by(user_login=login).delete()
        user.password_hash, user.access_right = None, "anonymized"
        db.session.commit()
        self._audit.record(login, "ANONYMIZE", "OK")
        return AnonymizationResult("ANONYMIZED", subject_ref(login))

    # ---- маскування та журнал ------------------------------------------------------------
    def mask_text(self, text) -> str:
        return self._masker(text)

    def recent_audit(self, limit=10) -> list:
        events = AuditEvent.query.order_by(AuditEvent.id.desc()).limit(limit).all()
        return [{"event": e.event_type, "result": e.result} for e in events]
