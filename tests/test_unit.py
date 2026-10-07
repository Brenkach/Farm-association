from datetime import date

from models import ProductOffer, User


def test_set_password_hashes_value():
    u = User(login="a", access_right="farmer")
    u.set_password("secret")
    assert u.password_hash != "secret"
    assert u.password_hash.startswith("pbkdf2:sha256")


def test_check_password_correct_and_wrong():
    u = User(login="a", access_right="farmer")
    u.set_password("secret")
    assert u.check_password("secret") is True
    assert u.check_password("wrong") is False


def test_check_password_without_hash_is_false():
    assert User(login="a", access_right="farmer").check_password("x") is False


def test_same_password_gives_different_hashes():
    a, b = User(login="a", access_right="x"), User(login="b", access_right="x")
    a.set_password("same")
    b.set_password("same")
    assert a.password_hash != b.password_hash


def test_offer_total_value():
    o = ProductOffer(unit_price=12.5, quantity_available=4)
    assert o.total_value == 50.0


def test_offer_total_value_none_when_data_missing():
    assert ProductOffer(unit_price=None, quantity_available=4).total_value is None
    assert ProductOffer(unit_price=5, quantity_available=None).total_value is None


def test_offer_best_before():
    o = ProductOffer(produced_at=date(2026, 1, 1), shelf_life_days=10)
    assert o.best_before == date(2026, 1, 11)


def test_offer_best_before_none_without_shelf_life():
    assert ProductOffer(produced_at=date(2026, 1, 1), shelf_life_days=None).best_before is None