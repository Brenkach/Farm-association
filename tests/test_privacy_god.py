"""Лаб. 8: тести поведінки God Object (PrivacyGodService). Усі дані синтетичні."""
import pytest
from flask import Flask

from anonymization import AuditEvent, ProtectedAccount, UserNotFound
from consent import ConsentDenied, ConsentHistory, ConsentService, MarketingOutbox, UserConsent
from extensions import db
from models import User
from privacy_god import PrivacyGodService

MKT = "MARKETING_EMAIL"
ALICE, BOB, ROOT = "alice_test", "bob_test", "root_test"


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test-key", TESTING=True, SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'god_test.db'}")
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
def god(app):
    return PrivacyGodService()


def audit_events():
    return [(e.event_type, e.result) for e in AuditEvent.query.order_by(AuditEvent.id).all()]


# ----------------------------------------------------------------------------- згоди
def test_grant_creates_record_history_and_audit(god):
    assert god.grant_consent(ALICE, MKT) is True
    rec = ConsentService.get(ALICE, MKT)
    assert rec.is_granted and rec.policy_version
    assert [h.action for h in ConsentHistory.query.filter_by(user_login=ALICE).all()] == ["GRANT"]
    assert audit_events() == [("CONSENT_GRANT", "OK")]


def test_grant_is_idempotent(god):
    assert god.grant_consent(ALICE, MKT) is True
    assert god.grant_consent(ALICE, MKT) is False
    assert ConsentHistory.query.filter_by(user_login=ALICE).count() == 1


def test_grant_rejects_unknown_purpose(god):
    with pytest.raises(ValueError):
        god.grant_consent(ALICE, "SPAM")


def test_revoke_withdraws_consent_and_audits(god):
    ConsentService.grant(ALICE, MKT)
    assert god.revoke_consent(ALICE, MKT) is True
    assert ConsentService.get(ALICE, MKT).is_granted is False
    assert audit_events() == [("CONSENT_REVOKE", "OK")]


def test_revoke_without_consent_returns_false(god):
    assert god.revoke_consent(ALICE, MKT) is False


def test_status_explains_the_decision(god):
    assert god.consent_status(ALICE, MKT) == {"purpose": MKT, "granted": False, "reason": "NO_RECORD"}
    ConsentService.grant(ALICE, MKT)
    assert god.consent_status(ALICE, MKT)["granted"] is True


# ----------------------------------------------------------------------------- маркетинг
def test_marketing_is_denied_without_consent_and_audited(god):
    with pytest.raises(ConsentDenied):
        god.send_marketing(ALICE, "Promo")
    assert MarketingOutbox.query.count() == 0
    assert audit_events() == [("MARKETING_SEND", "DENIED")]


def test_marketing_is_sent_with_consent(god):
    ConsentService.grant(ALICE, MKT)
    assert god.send_marketing(ALICE, "x" * 500) > 0
    assert len(MarketingOutbox.query.one().message) == 200
    assert audit_events() == [("MARKETING_SEND", "OK")]


# ----------------------------------------------------------------------------- експорт
def test_export_self_returns_own_data(god):
    data = god.export_personal_data(ALICE, ALICE)
    assert data["login"] == ALICE and data["role"] == "farmer"
    assert audit_events() == [("DATA_EXPORT", "OK")]


def test_export_of_foreign_data_is_forbidden_and_audited(god):
    with pytest.raises(PermissionError):
        god.export_personal_data(ALICE, BOB)
    assert audit_events() == [("DATA_EXPORT", "DENIED")]


def test_privileged_actor_exports_requested_subject(god):
    assert god.export_personal_data(ROOT, BOB)["login"] == BOB


def test_export_of_missing_user_raises(god):
    with pytest.raises(UserNotFound):
        god.export_personal_data(ROOT, "nobody")


# ----------------------------------------------------------------------------- анонімізація
def test_anonymize_withdraws_consents_deletes_outbox_and_audits(god):
    ConsentService.grant(ALICE, MKT)
    god.send_marketing(ALICE, "Hello")
    audit_before = len(audit_events())
    result = god.anonymize_user(ALICE)
    assert result.status == "ANONYMIZED"
    assert db.session.get(User, ALICE).access_right == "anonymized"
    assert UserConsent.query.filter_by(user_login=ALICE, is_granted=True).count() == 0
    assert MarketingOutbox.query.filter_by(user_login=ALICE).count() == 0
    assert audit_events()[audit_before:] == [("ANONYMIZE", "OK")]


def test_anonymize_protects_system_accounts(god):
    with pytest.raises(ProtectedAccount):
        god.anonymize_user(ROOT)


def test_anonymize_twice_reports_already_anonymized(god):
    god.anonymize_user(BOB)
    assert god.anonymize_user(BOB).status == "ALREADY_ANONYMIZED"


# ----------------------------------------------------------------------------- маскування та журнал
def test_mask_text_hides_phone_numbers(god):
    assert "+380501112233" not in god.mask_text("call +380501112233")


def test_recent_audit_lists_latest_events_first(god):
    db.session.add_all([AuditEvent(event_type="A", subject_ref="s", actor_ref="x", result="OK"),
                        AuditEvent(event_type="B", subject_ref="s", actor_ref="x", result="OK")])
    db.session.commit()
    assert [e["event"] for e in god.recent_audit(limit=2)] == ["B", "A"]
