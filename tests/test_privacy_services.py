"""Лаб. 8: тести декомпозованих сервісів приватності. Усі дані синтетичні.

Залежності підміняються заглушками через конструктор (Dependency Injection): тест не знає
про AuditTrail, ConsentPolicyGate чи sanitize_text, а працює лише з контрактами.
"""
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest
from flask import Flask

from anonymization import AuditEvent, ProtectedAccount, UserNotFound
from consent import ConsentDenied, ConsentHistory, ConsentService, Decision, MarketingOutbox, UserConsent
from extensions import db
from models import User
from privacy_services import (
    AuditTrailSink, ConsentManager, ConsentPolicy, ErasureService, GateConsentChecker,
    MarketingDispatcher, PersonalDataExporter, build_default_services, recent_audit,
)

MKT = "MARKETING_EMAIL"
ALICE, BOB, ROOT = "alice_test", "bob_test", "root_test"
FIXED = datetime(2026, 1, 2, 3, 4, 5)


class FakeAudit:
    def __init__(self):
        self.events = []

    def record(self, subject, event_type, result):
        self.events.append((event_type, result))


class FixedClock:
    def now(self):
        return FIXED


class FakeConsents:
    def __init__(self, allowed):
        self._allowed = allowed

    def check(self, login, purpose):
        return Decision(self._allowed, "FAKE")


class StarMasker:
    def mask(self, text):
        return "***"


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test-key", TESTING=True, SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'services_test.db'}")
    db.init_app(app)
    with app.app_context():
        db.create_all()
        for login, role in ((ALICE, "farmer"), (BOB, "farmer"), (ROOT, "superuser")):
            u = User(login=login, access_right=role)
            u.set_password("Test-Pass-1!")
            db.session.add(u)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def audit():
    return FakeAudit()


# ----------------------------------------------------------------------------- ConsentManager
def test_grant_records_consent_history_and_audit(app, audit):
    manager = ConsentManager(ConsentPolicy(), FixedClock(), audit)
    assert manager.grant(ALICE, MKT) is True
    rec = ConsentService.get(ALICE, MKT)
    assert rec.is_granted and rec.granted_at == FIXED          # час прийшов із підміненого годинника
    assert [h.action for h in ConsentHistory.query.filter_by(user_login=ALICE)] == ["GRANT"]
    assert audit.events == [("CONSENT_GRANT", "OK")]


def test_grant_is_idempotent(app, audit):
    manager = ConsentManager(ConsentPolicy(), FixedClock(), audit)
    assert manager.grant(ALICE, MKT) is True
    assert manager.grant(ALICE, MKT) is False
    assert ConsentHistory.query.filter_by(user_login=ALICE).count() == 1


def test_unknown_purpose_is_rejected_by_grant_and_revoke(app, audit):
    manager = ConsentManager(ConsentPolicy(), FixedClock(), audit)
    with pytest.raises(ValueError):
        manager.grant(ALICE, "SPAM")
    with pytest.raises(ValueError):
        manager.revoke(ALICE, "SPAM")


def test_policy_comes_from_constructor_not_from_global_state(app, audit):
    manager = ConsentManager(ConsentPolicy(purposes=("CUSTOM",), version="v-test"), FixedClock(), audit)
    assert manager.grant(ALICE, "CUSTOM") is True
    assert UserConsent.query.filter_by(user_login=ALICE, purpose="CUSTOM").one().policy_version == "v-test"


def test_revoke_withdraws_consent_and_audits(app, audit):
    manager = ConsentManager(ConsentPolicy(), FixedClock(), audit)
    manager.grant(ALICE, MKT)
    assert manager.revoke(ALICE, MKT) is True
    assert ConsentService.get(ALICE, MKT).is_granted is False
    assert audit.events[-1] == ("CONSENT_REVOKE", "OK")


def test_revoke_without_consent_returns_false(app, audit):
    assert ConsentManager(ConsentPolicy(), FixedClock(), audit).revoke(ALICE, MKT) is False


# ----------------------------------------------------------------------------- MarketingDispatcher
def test_marketing_is_denied_when_checker_says_no(app, audit):
    dispatcher = MarketingDispatcher(FakeConsents(False), audit)
    with pytest.raises(ConsentDenied):
        dispatcher.send(ALICE, "Promo")
    assert MarketingOutbox.query.count() == 0
    assert audit.events == [("MARKETING_SEND", "DENIED")]


def test_marketing_works_with_any_consent_checker(app, audit):
    """Dependency Inversion: диспетчер не звертається до таблиць згод, лише до контракту."""
    dispatcher = MarketingDispatcher(FakeConsents(True), audit)
    assert dispatcher.send(ALICE, "x" * 500) > 0
    assert len(MarketingOutbox.query.one().message) == 200
    assert UserConsent.query.count() == 0


def test_broadcast_reaches_only_users_with_active_consent(app, audit):
    ConsentManager(ConsentPolicy(), FixedClock(), audit).grant(ALICE, MKT)
    dispatcher = MarketingDispatcher(GateConsentChecker(), audit)
    assert dispatcher.broadcast([ALICE, BOB], "Sale") == 1
    assert [m.user_login for m in MarketingOutbox.query.all()] == [ALICE]


# ----------------------------------------------------------------------------- PersonalDataExporter
def test_export_self_returns_masked_data(app, audit):
    exporter = PersonalDataExporter(StarMasker(), audit)
    data = exporter.export(ALICE, ALICE)
    assert data["login"] == "***" and data["role"] == "farmer"
    assert audit.events == [("DATA_EXPORT", "OK")]


def test_export_of_foreign_data_is_forbidden(app, audit):
    with pytest.raises(PermissionError):
        PersonalDataExporter(StarMasker(), audit).export(ALICE, BOB)
    assert audit.events == [("DATA_EXPORT", "DENIED")]


def test_privileged_actor_exports_the_requested_subject_not_himself(app, audit):
    """Регресія з лаби 7: адмін отримує дані запитаного користувача."""
    data = PersonalDataExporter(StarMasker(), audit).export(ROOT, BOB)
    assert data["role"] == "farmer"           # BOB, а не superuser


def test_export_of_missing_user_raises(app, audit):
    with pytest.raises(UserNotFound):
        PersonalDataExporter(StarMasker(), audit).export(ROOT, "nobody")


def test_describe_masks_through_injected_masker(app, audit):
    assert PersonalDataExporter(StarMasker(), audit).describe(ALICE) == "***"
    assert audit.events == [("DATA_DESCRIBE", "OK")]


# ----------------------------------------------------------------------------- ErasureService
def test_anonymize_withdraws_consents_deletes_outbox_and_audits(app, audit):
    ConsentManager(ConsentPolicy(), FixedClock(), audit).grant(ALICE, MKT)
    MarketingDispatcher(FakeConsents(True), audit).send(ALICE, "Hello")
    audit.events.clear()
    result = ErasureService(audit).anonymize(ALICE)
    assert result.status == "ANONYMIZED"
    assert db.session.get(User, ALICE).access_right == "anonymized"
    assert UserConsent.query.filter_by(user_login=ALICE, is_granted=True).count() == 0
    assert MarketingOutbox.query.filter_by(user_login=ALICE).count() == 0
    assert audit.events == [("ANONYMIZE", "OK")]


def test_anonymize_protects_system_accounts(app, audit):
    with pytest.raises(ProtectedAccount):
        ErasureService(audit).anonymize(ROOT)


def test_protected_roles_come_from_constructor(app, audit):
    with pytest.raises(ProtectedAccount):
        ErasureService(audit, protected_roles=("farmer",)).anonymize(ALICE)


def test_anonymize_twice_reports_already_anonymized(app, audit):
    service = ErasureService(audit)
    service.anonymize(BOB)
    assert service.anonymize(BOB).status == "ALREADY_ANONYMIZED"


def test_plan_lists_entities_without_changing_anything(app, audit):
    ConsentManager(ConsentPolicy(), FixedClock(), audit).grant(ALICE, MKT)
    assert ErasureService(audit).plan(ALICE) == ["users", "user_consents"]
    assert db.session.get(User, ALICE).access_right == "farmer"


# ----------------------------------------------------------------------------- адаптери та композиція
def test_audit_adapter_isolates_the_signature_of_the_trail(app):
    """Єдине місце, що знає про параметр actor: решта класів про нього не чули."""
    AuditTrailSink(actor="SYSTEM").record(ALICE, "TEST_EVENT", "OK")
    event = AuditEvent.query.one()
    assert (event.event_type, event.result) == ("TEST_EVENT", "OK")
    assert event.actor_ref and event.subject_ref and ALICE not in (event.subject_ref, event.actor_ref)


def test_recent_audit_lists_latest_events_first(app):
    db.session.add_all([AuditEvent(event_type="A", subject_ref="s", actor_ref="x", result="OK"),
                        AuditEvent(event_type="B", subject_ref="s", actor_ref="x", result="OK")])
    db.session.commit()
    assert [e["event"] for e in recent_audit(limit=2)] == ["B", "A"]


def test_gate_checker_explains_the_decision(app):
    checker = GateConsentChecker()
    assert checker.status(ALICE, MKT) == {"purpose": MKT, "granted": False, "reason": "NO_RECORD"}


def test_policy_value_object_is_immutable():
    policy = ConsentPolicy()
    with pytest.raises(FrozenInstanceError):
        policy.version = "hacked"


def test_default_services_work_together_end_to_end(app):
    services = build_default_services()
    services.consents.grant(ALICE, MKT)
    assert services.marketing.send(ALICE, "Hi") > 0
    assert services.erasure.anonymize(ALICE).status == "ANONYMIZED"
    assert [e["event"] for e in recent_audit(limit=3)] == ["ANONYMIZE", "MARKETING_SEND", "CONSENT_GRANT"]
