"""Lab 4, Завдання 4: інтеграційні тести Consent Engine. Усі дані синтетичні."""
import pytest
from flask import Flask

from consent import (
    CURRENT_POLICY_VERSION, ConsentDenied, ConsentHistory, ConsentPolicyGate,
    ConsentService, MarketingOutbox, UserConsent, register_consent_routes,
    send_marketing_message,
)
from extensions import db
from models import User

MKT, ANA = "MARKETING_EMAIL", "OPTIONAL_ANALYTICS"
ALICE, BOB = "alice_test", "bob_test"
SEND = "/api/marketing/send-test"


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-key", TESTING=True, SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'consent_test.db'}",
    )
    db.init_app(app)
    register_consent_routes(app)
    with app.app_context():
        db.create_all()
        for login in (ALICE, BOB):
            u = User(login=login, access_right="farmer")
            u.set_password("Test-Pass-1!")
            db.session.add(u)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def client_for(app, login):
    c = app.test_client()
    with c.session_transaction() as s:
        s["login"] = login
    return c


def grant(c, purpose, **body):
    return c.post(f"/api/consents/{purpose}/grant", json=body)


def revoke(c, purpose, **body):
    return c.post(f"/api/consents/{purpose}/revoke", json=body)


def outbox_count():
    return MarketingOutbox.query.count()


def history(login, purpose):
    return (ConsentHistory.query.filter_by(user_login=login, purpose=purpose)
            .order_by(ConsentHistory.id).all())


def record(login, purpose):
    return (UserConsent.query.populate_existing()
            .filter_by(user_login=login, purpose=purpose).one())


# ---------------- Основний сценарій GRANT -> ALLOW -> REVOKE -> DENY ----------------
def test_grant_allow_revoke_deny_scenario(app):
    c = client_for(app, ALICE)

    r = c.post(SEND)                                   # початковий стан: DENY
    assert r.status_code == 403 and r.get_json()["reason"] == "NO_RECORD"
    assert outbox_count() == 0

    r = grant(c, MKT, source="web_ui")                 # GRANT
    assert r.status_code == 200 and r.get_json()["changed"] is True

    r = c.post(SEND)                                   # ALLOW + побічний ефект
    assert r.status_code == 200 and r.get_json()["status"] == "SENT"
    assert outbox_count() == 1

    r = revoke(c, MKT, source="settings")              # REVOKE
    assert r.status_code == 200 and r.get_json()["changed"] is True

    r = c.post(SEND)                                   # DENY, без побічного ефекту
    assert r.status_code == 403 and r.get_json()["reason"] == "WITHDRAWN"
    assert outbox_count() == 1


def test_consent_for_one_purpose_does_not_allow_another(app):
    c = client_for(app, ALICE)
    assert grant(c, ANA).status_code == 200
    r = c.post(SEND)                                   # потрібна MARKETING_EMAIL
    assert r.status_code == 403 and r.get_json()["reason"] == "NO_RECORD"
    assert outbox_count() == 0
    gate = ConsentPolicyGate()
    assert gate.check(ALICE, ANA).allowed is True
    assert gate.check(ALICE, MKT).allowed is False


def test_consent_of_one_user_does_not_apply_to_another(app):
    assert grant(client_for(app, ALICE), MKT).status_code == 200
    r = client_for(app, BOB).post(SEND)
    assert r.status_code == 403
    assert outbox_count() == 0


# ---------------- Доказ і історія ----------------
def test_evidence_metadata_and_history(app):
    c = client_for(app, ALICE)
    grant(c, MKT, source="web_ui")
    rec = record(ALICE, MKT)
    assert rec.is_granted and rec.policy_version == CURRENT_POLICY_VERSION
    assert rec.source == "web_ui" and rec.granted_at and rec.withdrawn_at is None

    revoke(c, MKT, source="settings")
    rec = record(ALICE, MKT)
    assert not rec.is_granted and rec.withdrawn_at is not None and rec.source == "settings"

    rows = history(ALICE, MKT)
    assert [(h.action, h.source, h.policy_version) for h in rows] == [
        ("GRANT", "web_ui", CURRENT_POLICY_VERSION),
        ("REVOKE", "settings", CURRENT_POLICY_VERSION),
    ]
    api = c.get("/api/consents/history").get_json()["history"]
    assert [h["action"] for h in api] == ["GRANT", "REVOKE"]


# ---------------- Ідемпотентність ----------------
def test_grant_is_idempotent(app):
    c = client_for(app, ALICE)
    assert grant(c, MKT).get_json()["changed"] is True
    assert grant(c, MKT).get_json()["changed"] is False
    assert len(history(ALICE, MKT)) == 1


def test_revoke_is_idempotent_and_creates_no_contradictions(app):
    c = client_for(app, ALICE)
    assert revoke(c, MKT).get_json()["changed"] is False       # немає що відкликати
    assert UserConsent.query.count() == 0 and len(history(ALICE, MKT)) == 0
    grant(c, MKT)
    assert revoke(c, MKT).get_json()["changed"] is True
    assert revoke(c, MKT).get_json()["changed"] is False
    assert UserConsent.query.filter_by(user_login=ALICE).count() == 1
    assert [h.action for h in history(ALICE, MKT)] == ["GRANT", "REVOKE"]


# ---------------- Валідація, авторизація, версія політики ----------------
def test_unknown_purpose_and_invalid_source_are_rejected(app):
    c = client_for(app, ALICE)
    assert grant(c, "SELL_MY_DATA").status_code == 400
    assert revoke(c, "SELL_MY_DATA").status_code == 400
    assert grant(c, MKT, source="hacker").status_code == 400
    assert UserConsent.query.count() == 0


def test_unauthenticated_requests_get_401(app):
    c = app.test_client()
    assert c.get("/api/consents").status_code == 401
    assert grant(c, MKT).status_code == 401
    assert revoke(c, MKT).status_code == 401
    assert c.post(SEND).status_code == 401
    assert UserConsent.query.count() == 0


def test_session_of_nonexistent_user_is_rejected(app):
    c = client_for(app, "ghost_user")
    assert grant(c, MKT).status_code == 401


def test_outdated_policy_version_is_denied(app):
    c = client_for(app, ALICE)
    r = grant(c, MKT, policy_version="2020-old")        # клієнт прийняв стару політику
    assert r.status_code == 409 and UserConsent.query.count() == 0

    grant(c, MKT)                                       # а тепер згода застаріла в БД
    rec = record(ALICE, MKT)
    rec.policy_version = "2020-old"
    db.session.commit()
    r = c.post(SEND)
    assert r.status_code == 403 and r.get_json()["reason"] == "POLICY_VERSION_MISMATCH"
    assert outbox_count() == 0


# ---------------- Background job / без кешу ----------------
def test_background_job_rechecks_current_consent(app):
    ConsentService.grant(ALICE, MKT, "api")
    assert send_marketing_message(ALICE, "job #1") > 0
    ConsentService.revoke(ALICE, MKT, "api")             # відкликання між постановкою і виконанням
    with pytest.raises(ConsentDenied) as exc:
        send_marketing_message(ALICE, "job #2")
    assert exc.value.decision.reason == "WITHDRAWN"
    assert outbox_count() == 1


def test_list_endpoint_shows_all_purposes(app):
    c = client_for(app, ALICE)
    grant(c, ANA)
    data = c.get("/api/consents").get_json()
    by = {x["purpose"]: x for x in data["consents"]}
    assert set(by) == {MKT, ANA}
    assert by[ANA]["is_granted"] is True and by[MKT]["is_granted"] is False
    assert data["current_policy_version"] == CURRENT_POLICY_VERSION
