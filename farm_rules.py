"""Data-driven валідація редагування господарства (Лаб. 6, PASS-стан).

Умови, які раніше жили в ланцюжку вкладених if/elif всередині маршруту, винесено у
статичну таблицю RULES. Порядок рядків у таблиці = порядок перевірок: перша істинна
умова дає повідомлення про помилку, наступні не обчислюються.
"""
from datetime import date
from operator import itemgetter

PHONE_LENGTHS = range(9, 16)      # допустима довжина телефону: 9..15 символів
MAX_PERMIT_DAYS = 5 * 365         # максимальний термін дозволу


def _phone(form):
    return form.get("phone", "").strip()


def _date(form, key):
    return date.fromisoformat(form.get(key))


# (умова-предикат, повідомлення про помилку)
RULES = (
    (lambda f: not f.get("permit_issued_at") or not f.get("permit_expires_at"),
     "Поля дат дозволу є обов'язковими!"),
    (lambda f: bool(_phone(f)) and len(_phone(f)) not in PHONE_LENGTHS,
     "Телефон повинен містити лише цифри (9–15 символів)."),
    (lambda f: _date(f, "permit_expires_at") < _date(f, "permit_issued_at"),
     "Дата завершення дозволу не може бути раніше дати видачі!"),
    (lambda f: (_date(f, "permit_expires_at") - _date(f, "permit_issued_at")).days > MAX_PERMIT_DAYS,
     "Термін дозволу не може перевищувати 5 років!"),
    (lambda f: _date(f, "permit_expires_at") < date.today(),
     "Дозвіл уже прострочений!"),
    (lambda f: not f.get("region") or not f.get("farmer_fullname"),
     "Вкажіть регіон і ПІБ фермера!"),
)


def first_error(form):
    """Повідомлення першої порушеної умови або None. Без жодного if/for у тілі."""
    return next(map(itemgetter(1), filter(lambda rule: rule[0](form), RULES)), None)
