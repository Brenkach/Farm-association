from datetime import date

from extensions import db
from models import Employee, Farm, ProductOffer, ProductType, User
from tests.conftest import login


def text(resp):
    return resp.get_data(as_text=True)


# ---------- Автентифікація ----------

def test_index_redirects_anonymous_to_login(client):
    r = client.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_success_sets_session(client, seed):
    r = login(client, "farmer1")
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert s["login"] == "farmer1"
        assert s["access_right"] == "farmer"
        assert s["farm_id"] == seed["farm1"]


def test_login_wrong_password(client, seed):
    r = login(client, "farmer1", "wrong")
    assert r.status_code == 200
    assert "Невірний логін або пароль" in text(r)


def test_logout_clears_session(client, seed):
    login(client, "farmer1")
    client.get("/logout")
    with client.session_transaction() as s:
        assert "login" not in s


def test_protected_page_requires_login(client, seed):
    assert client.get("/farms").status_code == 302


# ---------- Реєстрація ----------

def reg_data(**over):
    d = {"login": "newfarmer", "password": "abc12345", "confirm": "abc12345",
         "farm_name": "Нова ферма", "specialization_id": "1",
         "farmer_fullname": "Іван Іванов", "region": "Чернівецька",
         "address": "вул. Тестова 1", "phone": "380501234567",
         "permit_issued_at": "2025-01-01", "permit_expires_at": "2030-01-01"}
    d.update(over)
    return d


def test_register_creates_user_and_farm(client, seed):
    r = client.post("/register", data=reg_data(specialization_id=str(seed["spec_id"])))
    assert r.status_code == 302
    u = db.session.get(User, "newfarmer")
    assert u is not None and u.access_right == "farmer" and u.farm_id is not None


def test_register_duplicate_login(client, seed):
    r = client.post("/register", data=reg_data(login="admin", specialization_id=str(seed["spec_id"])))
    assert "Такий логін уже існує" in text(r)


def test_register_password_mismatch(client, seed):
    r = client.post("/register", data=reg_data(confirm="other", specialization_id=str(seed["spec_id"])))
    assert "Паролі не співпадають" in text(r)


def test_register_expiry_before_issue(client, seed):
    r = client.post("/register", data=reg_data(
        specialization_id=str(seed["spec_id"]),
        permit_issued_at="2030-01-01", permit_expires_at="2025-01-01"))
    assert "не може бути раніше" in text(r)
    assert db.session.get(User, "newfarmer") is None


def test_reset_password_changes_hash(client, seed):
    client.post("/reset-password", data={"login": "farmer1", "password": "newpass1", "confirm": "newpass1"})
    db.session.expire_all()
    assert db.session.get(User, "farmer1").check_password("newpass1")


def test_reset_password_unknown_user(client, seed):
    r = client.post("/reset-password", data={"login": "ghost", "password": "x", "confirm": "x"})
    assert "не знайдено" in text(r)


# ---------- Господарства та права доступу ----------

def farm_form(seed, **over):
    d = {"name": "Створена ферма", "specialization_id": str(seed["spec_id"]),
         "farmer_fullname": "Петро", "region": "Київська", "address": "адреса",
         "phone": "380671234567", "permit_issued_at": "2025-01-01",
         "permit_expires_at": "2030-01-01"}
    d.update(over)
    return d


def test_superuser_creates_farm(client, seed):
    login(client, "admin")
    r = client.post("/farms", data=farm_form(seed))
    assert r.status_code == 302
    assert Farm.query.filter_by(name="Створена ферма").count() == 1


def test_farm_invalid_phone_rejected(client, seed):
    login(client, "admin")
    r = client.post("/farms", data=farm_form(seed, phone="123"))
    assert "Телефон" in text(r)
    assert Farm.query.filter_by(name="Створена ферма").count() == 0


def test_worker_cannot_create_farm(client, seed):
    login(client, "worker1")
    r = client.post("/farms", data=farm_form(seed))
    assert r.status_code == 302 and "/forbidden" in r.headers["Location"]


def test_farmer_cannot_edit_foreign_farm(client, seed):
    login(client, "farmer1")
    r = client.get(f"/farms/{seed['farm2']}/edit")
    assert r.status_code == 302 and "/forbidden" in r.headers["Location"]


def test_farmer_can_open_own_farm_edit(client, seed):
    login(client, "farmer1")
    assert client.get(f"/farms/{seed['farm1']}/edit").status_code == 200


def test_superuser_deletes_farm(client, seed):
    login(client, "admin")
    client.get(f"/farms/{seed['farm2']}/delete")
    db.session.expire_all()
    assert db.session.get(Farm, seed["farm2"]) is None


def test_farmer_cannot_delete_farm(client, seed):
    login(client, "farmer1")
    r = client.get(f"/farms/{seed['farm1']}/delete")
    assert r.status_code == 302
    db.session.expire_all()
    assert db.session.get(Farm, seed["farm1"]) is not None


# ---------- Пропозиції ----------

def offer_form(seed, **over):
    d = {"specialization_id": str(seed["spec_id"]), "product_name": "Яблука",
         "uom": "кг", "unit_price": "25.5", "quantity_available": "100",
         "shelf_life_days": "30", "produced_at": date.today().isoformat(),
         "note": "тест"}
    d.update(over)
    return d


def test_farmer_creates_offer_and_product_type(client, seed):
    login(client, "farmer1")
    r = client.post("/offers", data=offer_form(seed))
    assert r.status_code == 302
    assert ProductOffer.query.count() == 1
    assert ProductType.query.filter_by(product_name="Яблука", name="Ферма 1").count() == 1


def test_offer_negative_price_rejected(client, seed):
    login(client, "farmer1")
    r = client.post("/offers", data=offer_form(seed, unit_price="-5"))
    assert r.status_code == 200          # без редіректу, форма не прийнята
    assert ProductOffer.query.count() == 0


def test_worker_cannot_create_offer(client, seed):
    login(client, "worker1")
    r = client.post("/offers", data=offer_form(seed))
    assert "/forbidden" in r.headers["Location"]
    assert ProductOffer.query.count() == 0


# ---------- Працівники ----------

def test_farmer_creates_employee_with_worker_account(client, seed):
    login(client, "farmer1")
    r = client.post("/employees", data={
        "full_name": "Олена Коваль", "position": "Оператор", "hire_date": "2025-03-01",
        "monthly_salary": "15000", "address": "адреса", "phone": "380931234567",
        "account_login": "olena", "account_password": "workerpass1"})
    assert r.status_code == 200
    assert Employee.query.filter_by(full_name="Олена Коваль").count() == 1
    u = db.session.get(User, "olena")
    assert u.access_right == "worker" and u.farm_id == seed["farm1"]
    assert u.check_password("workerpass1")