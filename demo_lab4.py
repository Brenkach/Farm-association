#!/usr/bin/env python3
"""Лабораторна №4: сценарій живої демонстрації (4 кроки, ~5 хвилин).

Запуск з кореня проєкту (Docker і база вже підняті):
    python demo_lab4.py              # з паузами між кроками (Enter)
    python demo_lab4.py --no-pause   # прогін без пауз (для репетиції)
    python demo_lab4.py --only 3     # лише один крок

Пароль адміна береться зі змінної ADMIN_PASSWORD (.env) або запитується.
Усі дані синтетичні; створені демо-користувачі наприкінці анонімізуються.
"""
import argparse
import getpass
import io
import json
import logging
import os
import re
import secrets
import subprocess
import sys

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE = os.getenv("DEMO_BASE_URL", "http://localhost:5001").rstrip("/")
PG_USER = os.getenv("DEMO_PG_USER", "postgres")
PG_DB = os.getenv("DEMO_PG_DB", "farm_db")
NO_PAUSE = False
COL = dict(b="\033[1m", g="\033[92m", y="\033[93m", r="\033[91m", c="\033[96m", e="\033[0m")


# ----------------------------- утиліти виводу -----------------------------
def say(text, col="c"):
    print(f"{COL[col]}{text}{COL['e']}")


def banner(text):
    print(f"\n{COL['b']}{'=' * 72}\n{text}\n{'=' * 72}{COL['e']}")


def pause():
    if not NO_PAUSE:
        input(f"{COL['y']}\n[Enter - далі] {COL['e']}")


def call(sess, method, path, pretty=False, quiet=False, **kw):
    try:
        r = sess.request(method, BASE + path, allow_redirects=False, timeout=15, **kw)
    except requests.ConnectionError:
        sys.exit(f"Сервіс недоступний ({BASE}). Запустіть: docker compose up -d")
    if not quiet:
        say(f"$ {method} {path}  ->  HTTP {r.status_code}", "g" if r.status_code < 400 else "r")
        try:
            data = r.json()
            print(json.dumps(data, ensure_ascii=False, indent=2 if pretty else None))
        except ValueError:
            print(r.text[:200])
    return r


def sh(cmd, show_cmd=True):
    if show_cmd:
        say("$ " + " ".join(cmd), "c")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        say(f"(команда '{cmd[0]}' недоступна)", "y")
        return ""
    out = (p.stdout + p.stderr).strip()
    print(out)
    return out


def psql(sql):
    say(f"psql> {sql}", "c")
    sh(["docker", "compose", "exec", "-T", "db", "psql", "-U", PG_USER, "-d", PG_DB, "-c", sql],
       show_cmd=False)


def pytest(path):
    sh([sys.executable, "-m", "pytest", path, "-q", "-p", "no:cacheprovider"])


def app_logs(pattern, last=4):
    out = sh(["docker", "compose", "logs", "web", "--tail", "60", "--no-log-prefix"], show_cmd=False)
    lines = [l for l in out.splitlines() if re.search(pattern, l)]
    say("Рядки з логів застосунку (docker compose logs web):", "c")
    print("\n".join(lines[-last:]) or "(немає рядків)")


# ----------------------------- підготовка -----------------------------
def spec_id(sess):
    html = sess.get(BASE + "/register", timeout=15).text
    m = re.search(r'name="specialization_id"[^>]*>.*?<option[^>]*value="(\d+)"', html, re.S)
    return m.group(1) if m else "1"


def register(prefix):
    """Реєструє синтетичного фермера; повертає (сесія, логін)."""
    sess = requests.Session()
    login = f"{prefix}_{secrets.token_hex(3)}"
    pw = "Demo-" + secrets.token_hex(6)
    data = {
        "login": login, "password": pw, "confirm": pw,
        "farm_name": "Demo Farm " + secrets.token_hex(3), "specialization_id": spec_id(sess),
        "farmer_fullname": "Demo Farmer", "region": "Demo Region", "address": "Demo Street 1",
        "phone": "+380000000000", "permit_issued_at": "2026-01-01", "permit_expires_at": "2027-01-01",
    }
    r = sess.post(BASE + "/register", data=data, allow_redirects=False, timeout=15)
    if r.status_code != 302:
        sys.exit(f"Не вдалося зареєструвати демо-користувача (HTTP {r.status_code}).")
    return sess, login


def login_admin():
    pw = os.getenv("ADMIN_PASSWORD") or getpass.getpass("ADMIN_PASSWORD: ")
    sess = requests.Session()
    r = sess.post(BASE + "/login", data={"login": "admin", "password": pw},
                  allow_redirects=False, timeout=15)
    if r.status_code != 302:
        sys.exit("Не вдалося увійти як admin: перевірте ADMIN_PASSWORD "
                 "(для вже створеного адміна він міг лишитися старим).")
    return sess


# ----------------------------- КРОК 1 -----------------------------
def step1(ctx):
    banner("КРОК 1. Secure Logging: маскування PII і редагування секретів")
    sys.path.insert(0, os.getcwd())
    from privacy_logging import CorrelationIdFilter, PrivacyFilter, TEXT_FORMAT

    email, phone = "demo.user@example.com", "+380 50 000 00 00"
    password, token = "Demo-Secret-123", "tok_DEMO_abc123XYZ"

    def make(name, protected):
        lg = logging.getLogger(name)
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter(TEXT_FORMAT))
        h.addFilter(CorrelationIdFilter())
        if protected:
            h.addFilter(PrivacyFilter())
        lg.handlers, lg.propagate = [h], False
        lg.setLevel(logging.INFO)
        return lg

    for protected, title in ((False, "ДО захисту (звичайний logger):"),
                             (True, "ПІСЛЯ (централізований PrivacyFilter):")):
        say(title, "r" if not protected else "g")
        lg = make(f"demo.{protected}", protected)
        lg.info("op=REGISTER email=%s phone=%s password=%s token=%s", email, phone, password, token)
        lg.info("payload=%s", {"user": {"email": email, "password": password}, "op": "UPDATE"})
        try:
            problem = f"Cannot notify {email}: token={token}"
            raise ValueError(problem)
        except ValueError:
            lg.exception("Notification failed")
        print()
    say("Тест: оригінальних значень у тексті логу немає (позитивні й негативні сценарії):", "c")
    pytest("tests/test_secure_logging.py")

    call(ctx["a"], "GET", f"/api/users/{ctx['a_login']}/personal-data", quiet=True)
    app_logs(r"api/users/|consent op=")
    say("У живому логу логін у URL замаскований, correlation ID зберігається.", "g")


# ----------------------------- КРОК 2 -----------------------------
def step2(ctx):
    banner("КРОК 2. Personal Data Export + контроль доступу")
    a, a_login = ctx["a"], ctx["a_login"]
    call(a, "POST", "/api/consents/MARKETING_EMAIL/grant", quiet=True)
    call(a, "POST", "/api/marketing/send-test", quiet=True)

    say(f"Авторизований запит власних даних ({a_login}):", "c")
    call(a, "GET", f"/api/users/{a_login}/personal-data", pretty=True)
    say("Джерела секцій: profile <- users | farm_contact <- farms | employee_records <- employees\n"
        "                 activity <- marketing_outbox | consents <- user_consents + consent_history\n"
        "                 settings = documented omission | meta <- генерується (версія схеми, UTC)", "y")
    say("Хеша пароля та даних інших користувачів у відповіді немає (meta.excluded_fields).", "g")

    say("\nНегативний сценарій: той самий користувач просить ЧУЖИЙ профіль і неіснуючий:", "c")
    r1 = call(a, "GET", "/api/users/admin/personal-data")
    r2 = call(a, "GET", "/api/users/no_such_user/personal-data")
    same = r1.status_code == r2.status_code and r1.json() == r2.json()
    say("Відповіді ідентичні: факт існування чужого профілю не розкривається."
        if same else "УВАГА: відповіді відрізняються!", "g" if same else "r")
    pytest("tests/test_personal_data.py")


# ----------------------------- КРОК 3 -----------------------------
def sql_state(login, farm_id):
    psql(f"SELECT login, access_right FROM users WHERE login='{login}' OR farm_id={farm_id};")
    psql(f"SELECT farm_id, farmer_fullname, address, phone FROM farms WHERE farm_id={farm_id};")
    psql("SELECT user_login, purpose, is_granted, source FROM user_consents WHERE user_login IN "
         f"(SELECT login FROM users WHERE login='{login}' OR farm_id={farm_id});")
    psql("SELECT user_login, message FROM marketing_outbox WHERE user_login IN "
         f"(SELECT login FROM users WHERE login='{login}' OR farm_id={farm_id});")


def step3(ctx):
    banner("КРОК 3. Erasure / Anonymization workflow")
    a_login, farm_id = ctx["a_login"], ctx["farm_id"]
    say("Стан пов'язаних записів у БД ДО операції:", "c")
    sql_state(a_login, farm_id)

    say("\nСторонній користувач намагається анонімізувати чужий профіль:", "c")
    call(ctx["b"], "POST", f"/api/users/{a_login}/anonymize")

    say("\nАвторизований actor (admin) виконує анонімізацію, потім повторює запит:", "c")
    call(ctx["admin"], "POST", f"/api/users/{a_login}/anonymize")
    call(ctx["admin"], "POST", f"/api/users/{a_login}/anonymize")

    say("\nСтан БД ПІСЛЯ операції (PII немає, зв'язки цілі):", "c")
    sql_state(a_login, farm_id)
    say("\nPrivacy-safe audit (без логінів та імен):", "c")
    psql("SELECT id, event_type, subject_ref, actor_ref, result, correlation_id "
         "FROM audit_events ORDER BY id DESC LIMIT 2;")
    pytest("tests/test_anonymization.py")


# ----------------------------- КРОК 4 -----------------------------
def step4(ctx):
    banner("КРОК 4. Consent Policy Enforcement: GRANT -> ALLOW -> REVOKE -> DENY")
    b = ctx["b"]
    say("1) Початковий стан, залежна дія (маркетингова розсилка):", "c")
    call(b, "POST", "/api/marketing/send-test")
    say("\n1б) Згода на ІНШУ мету (OPTIONAL_ANALYTICS) не дозволяє розсилку:", "c")
    call(b, "POST", "/api/consents/OPTIONAL_ANALYTICS/grant", json={"source": "web_ui"})
    call(b, "POST", "/api/marketing/send-test")
    say("\n2) GRANT згоди на MARKETING_EMAIL:", "c")
    call(b, "POST", "/api/consents/MARKETING_EMAIL/grant", json={"source": "web_ui"})
    say("\n3) Та сама дія тепер дозволена (є побічний ефект, outbox_id):", "c")
    call(b, "POST", "/api/marketing/send-test")
    say("\n4) REVOKE тієї самої згоди:", "c")
    call(b, "POST", "/api/consents/MARKETING_EMAIL/revoke", json={"source": "settings"})
    say("\n5) Повтор дії: DENY, нового побічного ефекту немає:", "c")
    call(b, "POST", "/api/marketing/send-test")
    say("\nІсторія змін (доказ: політика, час, канал):", "c")
    call(b, "GET", "/api/consents/history", pretty=True)
    say("\nІнтеграційні тести, зокрема сценарій GRANT -> ALLOW -> REVOKE -> DENY:", "c")
    pytest("tests/test_consent.py")


# ----------------------------- main -----------------------------
def main():
    global NO_PAUSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pause", action="store_true", help="без пауз між кроками")
    ap.add_argument("--only", type=int, choices=[1, 2, 3, 4], help="виконати лише один крок")
    ap.add_argument("--keep", action="store_true", help="не очищати демо-користувачів")
    args = ap.parse_args()
    NO_PAUSE = args.no_pause

    try:
        requests.get(BASE + "/login", timeout=10)
    except requests.ConnectionError:
        sys.exit(f"Сервіс недоступний ({BASE}). Запустіть: docker compose up -d")

    say("Підготовка: вхід адміна і створення синтетичних користувачів...", "y")
    admin = login_admin()
    a, a_login = register("demo_a")
    b, b_login = register("demo_b")
    probe = call(a, "GET", f"/api/users/{a_login}/personal-data", quiet=True)
    ctx = {"admin": admin, "a": a, "a_login": a_login, "b": b, "b_login": b_login,
           "farm_id": probe.json()["profile"]["farm_id"]}

    steps = {1: step1, 2: step2, 3: step3, 4: step4}
    for n in ([args.only] if args.only else [1, 2, 3, 4]):
        pause()
        steps[n](ctx)

    if not args.keep:
        call(admin, "POST", f"/api/users/{b_login}/anonymize", quiet=True)
        if not args.only or args.only != 3:
            call(admin, "POST", f"/api/users/{a_login}/anonymize", quiet=True)
        say("\nОчищення: демо-користувачів анонімізовано.", "y")
    say("\nДемонстрацію завершено.", "g")


if __name__ == "__main__":
    main()
