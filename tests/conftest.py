import os
from datetime import date

import pytest

# Жорстко задаємо тестову БД (не setdefault), щоб не зачепити робочу
os.environ.update({
    "PG_USER": "postgres",
    "PG_PASSWORD": "postgrespassword",
    "PG_HOST": "localhost",
    "PG_PORT": "5433",
    "PG_DATABASE": "farm_test",
    "SECRET_KEY": "test",
})

from app import app as flask_app   # app.py не змінюємо
from extensions import db
from models import Specialization, Farm, User


@pytest.fixture()
def app():
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        # страховка: чистимо лише базу, назва якої закінчується на _test
        assert db.engine.url.database.endswith("_test")
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seed(app):
    """Спеціалізація, дві ферми та користувачі трьох ролей."""
    spec = Specialization(name="Тестова спеціалізація")
    db.session.add(spec)
    db.session.flush()

    def make_farm(name):
        f = Farm(name=name, specialization_id=spec.specialization_id,
                 permit_issued_at=date(2025, 1, 1),
                 permit_expires_at=date(2030, 1, 1))
        db.session.add(f)
        db.session.flush()
        return f

    farm1, farm2 = make_farm("Ферма 1"), make_farm("Ферма 2")

    for login_, role, farm in [("admin", "superuser", None),
                               ("farmer1", "farmer", farm1),
                               ("worker1", "worker", farm1)]:
        u = User(login=login_, access_right=role,
                 farm_id=farm.farm_id if farm else None)
        u.set_password("pass12345")
        db.session.add(u)

    db.session.commit()
    return {"spec_id": spec.specialization_id,
            "farm1": farm1.farm_id, "farm2": farm2.farm_id}


def login(client, user, password="pass12345"):
    return client.post("/login", data={"login": user, "password": password})
