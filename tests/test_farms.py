import os
import sys
from datetime import date, timedelta

import pytest
from flask import Flask

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routes
from extensions import db
from models import Farm, Specialization


@pytest.fixture
def app(monkeypatch):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-only"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    captured = {}

    def fake_render(template, **ctx):
        captured["template"] = template
        captured.update(ctx)
        return "rendered"

    monkeypatch.setattr(routes, "render_template", fake_render)
    routes.register_routes(app)
    app.captured = captured

    with app.app_context():
        db.create_all()
        db.session.add(Specialization(name="Овочівництво"))
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def login(client, role):
    with client.session_transaction() as s:
        s["login"] = "tester"
        s["access_right"] = role


def form(**overrides):
    data = {
        "name": "Test Farm",
        "specialization_id": "1",
        "farmer_fullname": "Ivan Ivanenko",
        "region": "Chernivtsi",
        "address": "Main st. 1",
        "phone": "380501234567",
        "permit_issued_at": "2026-01-01",
        "permit_expires_at": "2027-01-01",
    }
    data.update(overrides)
    return data


def farms_count(app):
    with app.app_context():
        return Farm.query.count()


def add_farm(app, name, expires):
    with app.app_context():
        db.session.add(Farm(name=name, specialization_id=1, permit_expires_at=expires))
        db.session.commit()


def test_post_creates_farm_for_superuser(app):
    client = app.test_client()
    login(client, "superuser")

    resp = client.post("/farms", data=form())

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/farms")
    assert farms_count(app) == 1


def test_post_forbidden_for_non_superuser(app):
    client = app.test_client()
    login(client, "farmer")

    resp = client.post("/farms", data=form())

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/forbidden")
    assert farms_count(app) == 0


def test_post_requires_permit_dates(app):
    client = app.test_client()
    login(client, "superuser")

    client.post("/farms", data=form(permit_issued_at=""))

    assert "обов'язковими" in app.captured["msg"]
    assert farms_count(app) == 0


def test_post_rejects_short_phone(app):
    client = app.test_client()
    login(client, "superuser")

    client.post("/farms", data=form(phone="123"))

    assert "Телефон" in app.captured["msg"]
    assert farms_count(app) == 0


def test_post_rejects_expiry_before_issue(app):
    client = app.test_client()
    login(client, "superuser")

    client.post("/farms", data=form(
        permit_issued_at="2026-06-01", permit_expires_at="2026-01-01"))

    assert "раніше" in app.captured["msg"]
    assert farms_count(app) == 0


def test_get_expiring_filter_and_counters(app):
    today = date.today()
    add_farm(app, "Soon", today + timedelta(days=30))
    add_farm(app, "Later", today + timedelta(days=400))
    client = app.test_client()
    login(client, "worker")

    client.get("/farms?filter=expiring")

    ctx = app.captured
    assert [f.name for f in ctx["farms"]] == ["Soon"]
    assert ctx["total_count"] == 2
    assert ctx["expiring_count"] == 1
    assert ctx["msg"] is None


def test_get_without_login_redirects_to_login(app):
    resp = app.test_client().get("/farms")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
