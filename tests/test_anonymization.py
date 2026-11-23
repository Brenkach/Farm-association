"""Lab 4, Завдання 3: інтеграційні тести Anonymization workflow. Усі дані синтетичні."""
import logging
from datetime import date

import pytest
import sqlalchemy as sa
from flask import Flask

import anonymization
from anonymization import ERASURE_POLICY, AuditEvent, register_anonymization_routes
from consent import (ConsentPolicyGate, ConsentService, MarketingOutbox, UserConsent,
                     register_consent_routes, send_marketing_message)
from extensions import db
from models import Employee, Farm, ProductOffer, ProductType, Specialization, User
from privacy_logging import init_correlation_id

FARMER, WORKER, ADMIN = "farmer_test", "worker_test", "admin_test"
FARMER_PII = [FARMER, "Ivan Testenko", "+380501112233", "Test Street 1"]
WORKER_PII = [WORKER, "Olena Workerenko", "+380503334455", "Worker Street 2"]


def url(login):
    return f"/api/users/{login}/anonymize"


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret-key-for-lab4", TESTING=True, SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'anon_test.db'}",
    )
    db.init_app(app)
    init_correlation_id(app)
    register_consent_routes(app)
    register_anonymization_routes(app)
    with app.app_context():
        db.create_all()
        spec = Specialization(name="Test specialization")
        db.session.add(spec)
        db.session.flush()
        farm = Farm(name="Test Farm", specialization_id=spec.specialization_id,
                    farmer_fullname="Ivan Testenko", region="Test Region",
                    address="Test Street 1", phone="+380501112233")
        db.session.add(farm)
        db.session.flush()
        for login, role, f in [(FARMER, "farmer", farm), (WORKER, "worker", farm), (ADMIN, "superuser", None)]:
            u = User(login=login, access_right=role, farm_id=f.farm_id if f else None)
            u.set_password("Test-Pass-1!")
            db.session.add(u)
        pt = ProductType(name="Test Farm", product_name="Test product",
                         specialization_id=spec.specialization_id)
        db.session.add(pt)
        db.session.flush()
        db.session.add(ProductOffer(farm_id=farm.farm_id, product_type_id=pt.product_type_id,
                                    uom="kg", note="Synthetic offer note"))
        db.session.add(Employee(farm_id=farm.farm_id, full_name="Olena Workerenko", position="Tester",
                                hire_date=date(2025, 1, 15), monthly_salary=12345.0,
                                address="Worker Street 2", phone="+380503334455", user_login=WORKER))
        db.session.commit()
        ConsentService.grant(FARMER, "MARKETING_EMAIL", "web_ui")
        ConsentService.grant(FARMER, "OPTIONAL_ANALYTICS", "settings")
        send_marketing_message(FARMER, "Synthetic promo")
        yield app
        db.session.remove()
        db.drop_all()


def client_for(app, login, **headers):
    c = app.test_client()
    with c.session_transaction() as s:
        s["login"] = login
    c.environ_base.update({f"HTTP_{k.upper().replace('-', '_')}": v for k, v in headers.items()})
    return c


def dump(exclude=()):
    """Стан усіх таблиць БД у вигляді відсортованого списку рядків."""
    rows = []
    for t in db.metadata.sorted_tables:
        if t.name not in exclude:
            rows += [f"{t.name}:{tuple(r)}" for r in db.session.execute(t.select()).fetchall()]
    return sorted(rows)


def anon_login():
    db.session.expire_all()
    return User.query.filter(User.login.like("anon-%")).one().login


def assert_no_pii(pii):
    text = "\n".join(dump())
    found = [p for p in pii if p in text]
    assert not found, f"Початкові PII лишились у БД: {found}"


# ---------------- Основний сценарій: працівник ----------------
def test_admin_anonymizes_worker_pii_removed_business_records_kept(app):
    r = client_for(app, ADMIN).post(url(WORKER))
    assert r.status_code == 200 and r.get_json()["status"] == "ANONYMIZED"
    new = anon_login()
    assert r.get_json()["anonymous_id"] == new

    assert db.session.get(User, WORKER) is None
    u = db.session.get(User, new)
    assert u.password_hash is None and u.access_right == "anonymized"
    assert not u.check_password("Test-Pass-1!")          # увійти більше неможливо

    e = Employee.query.one()
    assert (e.full_name, e.address, e.phone) == ("Anonymized employee", None, None)
    assert e.hire_date == date(2025, 1, 1)               # узагальнено
    assert e.position == "Tester" and e.monthly_salary == 12345.0   # RETAIN
    assert e.user_login == new and e.farm_id == u.farm_id

    assert_no_pii(WORKER_PII)                            # ніде в БД, включно з audit
    assert db.session.get(User, FARMER) is not None            # інші користувачі не зачеплені


def test_referential_integrity_after_anonymization(app):
    client_for(app, ADMIN).post(url(WORKER))
    assert db.session.execute(sa.text("PRAGMA foreign_key_check")).fetchall() == []
    orphans = (db.session.query(Employee)
               .outerjoin(User, Employee.user_login == User.login)
               .filter(Employee.user_login.isnot(None), User.login.is_(None)).count())
    assert orphans == 0
    # звітні запити працюють
    assert db.session.query(Employee, User).join(User, Employee.user_login == User.login).count() == 1
    assert db.session.query(ProductOffer).join(Farm).join(ProductType).count() == 1


# ---------------- Самовидалення фермера: непрямі джерела ----------------
def test_self_erasure_covers_indirect_sources(app):
    c = client_for(app, FARMER)
    r = c.post(url(FARMER))
    assert r.status_code == 200
    new = anon_login()

    farm = Farm.query.one()
    assert (farm.farmer_fullname, farm.address, farm.phone) == ("Anonymized farmer", None, None)
    assert farm.name == "Test Farm" and farm.region == "Test Region"         # RETAIN
    assert ProductOffer.query.count() == 1                                    # SKIP / RETAIN

    assert MarketingOutbox.query.count() == 0                                 # DELETE
    recs = UserConsent.query.filter_by(user_login=new).all()
    assert len(recs) == 2 and all(not x.is_granted and x.withdrawn_at for x in recs)
    from consent import ConsentHistory
    actions = sorted((h.action, h.source) for h in ConsentHistory.query.filter_by(user_login=new))
    assert actions.count(("REVOKE", "erasure")) == 2 and len(actions) == 4
    assert ConsentPolicyGate().check(new, "MARKETING_EMAIL").allowed is False

    assert_no_pii(FARMER_PII)
    assert db.session.get(User, WORKER) is not None and Employee.query.one().full_name == "Olena Workerenko"
    assert c.get("/api/consents").status_code == 401                          # сесію скинуто


# ---------------- Audit ----------------
def test_audit_event_is_privacy_safe_and_has_correlation_id(app):
    client_for(app, ADMIN, X_Correlation_ID="corr-erasure-1").post(url(WORKER))
    ev = AuditEvent.query.one()
    new = anon_login()
    assert (ev.event_type, ev.result, ev.subject_ref) == ("ERASURE", "OK", new)
    assert ev.actor_ref.startswith("ref_") and ev.actor_ref != ADMIN
    assert ev.correlation_id == "corr-erasure-1" and ev.occurred_at
    assert_no_pii(WORKER_PII)
    audit_rows = str(db.session.execute(AuditEvent.__table__.select()).fetchall())
    assert ADMIN not in audit_rows and WORKER not in audit_rows   # у audit немає логінів


def test_self_erasure_audit_has_no_link_to_old_login(app):
    client_for(app, FARMER).post(url(FARMER))
    ev = AuditEvent.query.one()
    assert ev.actor_ref == "SELF" and ev.subject_ref.startswith("anon-")


# ---------------- Ідемпотентність ----------------
def test_repeated_request_changes_nothing_and_is_controlled(app):
    c = client_for(app, ADMIN)
    assert c.post(url(WORKER)).status_code == 200
    new = anon_login()
    before = dump()

    r = c.post(url(WORKER))                                # старий логін уже не існує
    assert r.status_code == 404 and r.get_json() == {"error": "NOT_FOUND"}
    r = c.post(url(new))                                   # повтор для вже анонімного запису
    assert r.status_code == 200 and r.get_json()["status"] == "ALREADY_ANONYMIZED"

    assert dump() == before                                # PII не відновлено, нових рядків немає
    assert AuditEvent.query.count() == 1
    assert User.query.filter(User.login.like("anon-%")).count() == 1


# ---------------- Авторизація ----------------
def test_foreign_and_nonexistent_targets_are_denied_identically(app):
    before = dump()
    c = client_for(app, FARMER)
    existing, missing = c.post(url(WORKER)), c.post(url("no_such_user"))
    assert existing.status_code == missing.status_code == 403
    assert existing.get_json() == missing.get_json() == {"error": "FORBIDDEN"}
    assert dump() == before


def test_unauthenticated_and_get_requests_are_rejected(app):
    before = dump()
    anon = app.test_client()
    assert anon.post(url(WORKER)).status_code == 401
    assert client_for(app, ADMIN).get(url(WORKER)).status_code == 405   # лише POST
    assert dump() == before


def test_superuser_account_is_protected(app):
    before = dump()
    r = client_for(app, ADMIN).post(url(ADMIN))
    assert r.status_code == 409 and r.get_json() == {"error": "PROTECTED_ACCOUNT"}
    assert dump() == before


# ---------------- Атомарність ----------------
def test_partial_failure_rolls_back_everything(app, monkeypatch):
    before = dump(exclude=("audit_events",))

    def boom(old):
        raise RuntimeError("simulated failure Ivan Testenko")   # повідомлення з PII не повинне витекти

    monkeypatch.setattr(anonymization, "_delete_outbox", boom)
    r = client_for(app, ADMIN).post(url(FARMER))
    assert r.status_code == 500 and r.get_json() == {"error": "ANONYMIZATION_FAILED"}
    assert "Ivan" not in r.get_data(as_text=True)

    assert dump(exclude=("audit_events",)) == before        # жодних часткових змін
    assert User.query.filter(User.login.like("anon-%")).count() == 0
    ev = AuditEvent.query.one()
    assert (ev.result, ev.subject_ref) == ("FAILED", None)

    monkeypatch.undo()                                       # після збою операцію можна повторити
    assert client_for(app, ADMIN).post(url(FARMER)).status_code == 200


# ---------------- Логи і політика ----------------
def test_logs_contain_no_pii(app, caplog):
    caplog.set_level(logging.DEBUG)
    client_for(app, ADMIN).post(url(FARMER))
    client_for(app, WORKER).post(url("no_such_user"))
    text = caplog.text
    assert "result=ANONYMIZED" in text and "result=DENY" in text
    for p in FARMER_PII + WORKER_PII:
        assert p not in text, f"У лозі знайдено: {p}"


def test_policy_table_matches_documented_actions():
    actions = {a for a, _ in ERASURE_POLICY.values()}
    assert actions == {"DELETE", "ANONYMIZE", "RETAIN", "SKIP"}
    assert ERASURE_POLICY["users"][0] == "ANONYMIZE"
    assert ERASURE_POLICY["marketing_outbox"][0] == "DELETE"
