"""Lab 4, Завдання 2: інтеграційні тести Personal Data Export. Усі дані синтетичні."""
import logging

import pytest
from flask import Flask

from consent import ConsentService, register_consent_routes, send_marketing_message
from extensions import db
from models import Employee, Farm, Specialization, User
from personal_data import SCHEMA_VERSION, register_export_routes

FARMER, WORKER, ADMIN, OTHER = "farmer_test", "worker_test", "admin_test", "other_farmer"
FARMER_NAME, FARMER_PHONE, FARMER_ADDR = "Ivan Testenko", "+380501112233", "Test Street 1"
WORKER_NAME, WORKER_PHONE = "Olena Workerenko", "+380503334455"
OTHER_FARM, OTHER_PHONE = "Other Farm Test", "+380509998877"
FORBIDDEN_BODY = {"error": "FORBIDDEN"}


def url(login):
    return f"/api/users/{login}/personal-data"


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret-key-for-lab4", TESTING=True, SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'export_test.db'}",
    )
    db.init_app(app)
    register_consent_routes(app)
    register_export_routes(app)
    with app.app_context():
        db.create_all()
        spec = Specialization(name="Test specialization")
        db.session.add(spec)
        db.session.flush()
        farm1 = Farm(name="Test Farm", specialization_id=spec.specialization_id,
                     farmer_fullname=FARMER_NAME, region="Test Region",
                     address=FARMER_ADDR, phone=FARMER_PHONE)
        farm2 = Farm(name=OTHER_FARM, specialization_id=spec.specialization_id,
                     farmer_fullname="Petro Otherenko", phone=OTHER_PHONE)
        db.session.add_all([farm1, farm2])
        db.session.flush()
        for login, role, farm in [(FARMER, "farmer", farm1), (WORKER, "worker", farm1),
                                  (ADMIN, "superuser", None), (OTHER, "farmer", farm2)]:
            u = User(login=login, access_right=role, farm_id=farm.farm_id if farm else None)
            u.set_password("Test-Pass-1!")
            db.session.add(u)
        db.session.flush()
        from datetime import date
        db.session.add(Employee(farm_id=farm1.farm_id, full_name=WORKER_NAME, position="Tester",
                                hire_date=date(2025, 1, 15), monthly_salary=12345.0,
                                address="Worker Street 2", phone=WORKER_PHONE, user_login=WORKER))
        db.session.commit()
        ConsentService.grant(FARMER, "MARKETING_EMAIL", "web_ui")
        send_marketing_message(FARMER, "Synthetic promo")
        yield app
        db.session.remove()
        db.drop_all()


def client_for(app, login):
    c = app.test_client()
    with c.session_transaction() as s:
        s["login"] = login
    return c


# ---------------- Повнота і контракт ----------------
def test_owner_gets_complete_export_with_stable_contract(app):
    r = client_for(app, FARMER).get(url(FARMER))
    assert r.status_code == 200 and r.is_json
    d = r.get_json()
    assert set(d) == {"meta", "profile", "farm_contact", "employee_records", "settings",
                      "activity", "consents"}
    assert d["meta"]["schema_version"] == SCHEMA_VERSION
    assert d["meta"]["subject_id"] == FARMER and d["meta"]["timezone"] == "UTC"
    assert d["meta"]["generated_at"].endswith("Z")
    assert d["profile"]["login"] == FARMER and d["profile"]["farm_name"] == "Test Farm"
    assert d["farm_contact"]["farmer_fullname"] == FARMER_NAME
    assert d["farm_contact"]["phone"] == FARMER_PHONE
    assert d["employee_records"] == []
    # джерело consents
    cur = {c["purpose"]: c for c in d["consents"]["current"]}
    assert cur["MARKETING_EMAIL"]["is_granted"] is True
    assert cur["OPTIONAL_ANALYTICS"]["is_granted"] is False
    assert [h["action"] for h in d["consents"]["history"]] == ["GRANT"]
    # джерело activity
    assert [m["message"] for m in d["activity"]["marketing_messages"]] == ["Synthetic promo"]
    assert r.headers["Cache-Control"] == "no-store"


def test_worker_export_has_employee_record_but_no_farm_contact(app):
    d = client_for(app, WORKER).get(url(WORKER)).get_json()
    assert len(d["employee_records"]) == 1
    rec = d["employee_records"][0]
    assert rec["full_name"] == WORKER_NAME and rec["monthly_salary"] == 12345.0
    assert rec["phone"] == WORKER_PHONE and rec["hire_date"] == "2025-01-15"
    assert d["farm_contact"] == {}                       # дані фермера працівнику не віддаються
    assert FARMER_NAME not in str(d) and FARMER_PHONE not in str(d)


def test_schema_is_stable_for_user_without_data(app):
    d = client_for(app, ADMIN).get(url(ADMIN)).get_json()
    assert d["farm_contact"] == {} and d["employee_records"] == []
    assert d["activity"] == {"marketing_messages": []}
    assert d["consents"]["history"] == []
    assert len(d["consents"]["current"]) == 2            # усі purposes присутні
    assert d["settings"]["data"] == {}                   # documented omission
    assert d["profile"]["farm_id"] is None


# ---------------- Мінімізація ----------------
def test_export_contains_no_security_sensitive_or_foreign_data(app):
    for login in (FARMER, WORKER, ADMIN):
        body = client_for(app, login).get(url(login)).get_data(as_text=True)
        low = body.lower()
        assert "password" not in low and "pbkdf2" not in low and "token" not in low
        assert OTHER not in body and OTHER_FARM not in body and OTHER_PHONE not in body


# ---------------- Контроль доступу ----------------
def test_other_user_is_denied_without_any_data(app):
    r = client_for(app, FARMER).get(url(WORKER))
    assert r.status_code == 403 and r.get_json() == FORBIDDEN_BODY
    body = r.get_data(as_text=True)
    assert WORKER_NAME not in body and WORKER_PHONE not in body


def test_nonexistent_subject_is_indistinguishable_from_foreign_profile(app):
    c = client_for(app, FARMER)
    existing, missing = c.get(url(WORKER)), c.get(url("no_such_user"))
    assert existing.status_code == missing.status_code == 403
    assert existing.get_json() == missing.get_json() == FORBIDDEN_BODY


def test_privileged_role_can_export_any_user_and_gets_404_for_missing(app):
    c = client_for(app, ADMIN)
    r = c.get(url(WORKER))
    assert r.status_code == 200 and r.get_json()["meta"]["requested_by"] == ADMIN
    assert c.get(url("no_such_user")).status_code == 404


def test_unauthenticated_request_gets_401_without_data(app):
    r = app.test_client().get(url(FARMER))
    assert r.status_code == 401 and FARMER_NAME not in r.get_data(as_text=True)


def test_export_does_not_modify_data(app):
    c = client_for(app, FARMER)
    first = c.get(url(FARMER)).get_json()
    second = c.get(url(FARMER)).get_json()
    first["meta"].pop("generated_at"); second["meta"].pop("generated_at")
    assert first == second


# ---------------- Витік через логи ----------------
def test_export_logs_contain_no_pii_or_full_json(app, caplog):
    caplog.set_level(logging.DEBUG)
    client_for(app, FARMER).get(url(FARMER))             # успіх
    client_for(app, FARMER).get(url(WORKER))             # відмова
    client_for(app, ADMIN).get(url("no_such_user"))      # 404
    text = caplog.text
    assert "personal_data_export" in text and "result=OK" in text and "result=DENY" in text
    for secret in (FARMER, WORKER, ADMIN, FARMER_NAME, FARMER_PHONE, FARMER_ADDR,
                   WORKER_NAME, WORKER_PHONE, "12345", "schema_version", "Synthetic promo"):
        assert secret not in text, f"У лозі знайдено: {secret}"


# ---------------- Лаб. 7: захист від випадкової мутації змінної login ----------------
def test_privileged_export_returns_requested_subject_not_the_actor(app):
    """Якщо вхідний login перезаписано логіном actor, адмін отримає ДАНІ АДМІНА замість запитаних."""
    d = client_for(app, ADMIN).get(url(WORKER)).get_json()
    assert d["meta"]["subject_id"] == WORKER
    assert d["profile"]["login"] == WORKER
