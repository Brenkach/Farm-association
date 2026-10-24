"""Лаб. 6: таблична валідація farm_rules.RULES еквівалентна вихідній логіці (FAIL-стану)."""
import itertools
from datetime import date, timedelta

import pytest

from farm_rules import RULES, first_error


def oracle(form):
    """ЕТАЛОН: вихідна логіка з вкладеними if/elif (стан FAIL), повертає повідомлення або None."""
    permit_issued = form.get("permit_issued_at")
    permit_expires = form.get("permit_expires_at")
    phone_val = form.get("phone", "").strip()
    msg = None
    if not permit_issued or not permit_expires:
        msg = "Поля дат дозволу є обов'язковими!"
    else:
        if phone_val and (len(phone_val) < 9 or len(phone_val) > 15):
            msg = "Телефон повинен містити лише цифри (9–15 символів)."
        if not msg:
            issued_dt = date.fromisoformat(permit_issued)
            expires_dt = date.fromisoformat(permit_expires)
            if expires_dt < issued_dt:
                msg = "Дата завершення дозволу не може бути раніше дати видачі!"
            elif (expires_dt - issued_dt).days > 5 * 365:
                msg = "Термін дозволу не може перевищувати 5 років!"
            elif expires_dt < date.today():
                msg = "Дозвіл уже прострочений!"
            elif not form.get("region") or not form.get("farmer_fullname"):
                msg = "Вкажіть регіон і ПІБ фермера!"
    return msg


def outcome(fn, form):
    try:
        return ("msg", fn(form))
    except ValueError as e:                      # некоректний формат дати
        return ("ValueError", type(e).__name__)


def iso(delta_days):
    return (date.today() + timedelta(days=delta_days)).isoformat()


def test_table_is_equivalent_to_reference_logic_on_all_combinations():
    issued = [None, "", iso(-400), iso(-100), iso(30), "not-a-date"]
    expires = [None, "", iso(-500), iso(-50), iso(100), iso(2000), iso(-300), "x"]
    phones = [None, "", "   ", "12345678", "123456789", "1" * 15, "1" * 16, " 123456789 "]
    regions = [None, "", "Київська"]
    names = [None, "", "Іван Тестенко"]
    checked = 0
    for i, e, p, r, n in itertools.product(issued, expires, phones, regions, names):
        form = {k: v for k, v in {"permit_issued_at": i, "permit_expires_at": e, "phone": p,
                                  "region": r, "farmer_fullname": n}.items() if v is not None}
        assert outcome(first_error, form) == outcome(oracle, form), form
        checked += 1
    assert checked == 6 * 8 * 8 * 3 * 3


@pytest.mark.parametrize("form, expected", [
    ({}, "Поля дат дозволу є обов'язковими!"),
    ({"permit_issued_at": iso(-10), "permit_expires_at": iso(10), "phone": "123"},
     "Телефон повинен містити лише цифри (9–15 символів)."),
    ({"permit_issued_at": iso(10), "permit_expires_at": iso(5)},
     "Дата завершення дозволу не може бути раніше дати видачі!"),
    ({"permit_issued_at": iso(-10), "permit_expires_at": iso(6 * 365)},
     "Термін дозволу не може перевищувати 5 років!"),
    ({"permit_issued_at": iso(-400), "permit_expires_at": iso(-30)}, "Дозвіл уже прострочений!"),
    ({"permit_issued_at": iso(-10), "permit_expires_at": iso(300), "farmer_fullname": "Ф"},
     "Вкажіть регіон і ПІБ фермера!"),
    ({"permit_issued_at": iso(-10), "permit_expires_at": iso(300), "region": "Р"},
     "Вкажіть регіон і ПІБ фермера!"),
])
def test_each_rule_returns_its_message(form, expected):
    assert first_error(form) == expected


def test_valid_form_has_no_error():
    form = {"permit_issued_at": iso(-10), "permit_expires_at": iso(300), "phone": "380501112233",
            "region": "Київська", "farmer_fullname": "Іван Тестенко"}
    assert first_error(form) is None


def test_rules_are_evaluated_lazily_in_order():
    """Після першої помилки наступні умови не обчислюються (як у вихідному if/elif)."""
    form = {"permit_issued_at": "not-a-date", "permit_expires_at": "x", "phone": "1"}
    assert first_error(form) == "Телефон повинен містити лише цифри (9–15 символів)."


def test_table_has_expected_shape():
    assert len(RULES) == 6 and all(callable(c) and isinstance(m, str) for c, m in RULES)
