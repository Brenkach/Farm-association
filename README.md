# Farm-association

Веб-платформа асоціації фермерських господарств. Господарства ведуть профіль, перелік продукції, працівників і формують звіт по виробниках. Є контур приватності (GDPR): згоди, експорт даних, анонімізація, безпечне логування. Стек: Python 3.12, Flask, Flask-SQLAlchemy, PostgreSQL 15, Docker Compose.

## Швидкий старт (5 хвилин)

1. `cp .env.example .env` і заповніть значення (`SECRET_KEY`, `ADMIN_PASSWORD`, змінні `PG_*`). Файл `.env` не потрапляє в Git.
2. `docker compose up --build`
3. Відкрийте http://localhost:5001 і увійдіть як `admin` з паролем `ADMIN_PASSWORD`.
4. Тести: `pytest tests/ -v`

## Онбординг нового розробника

1. Прочитайте цей README, потім [docs/sdd.md](docs/sdd.md): компоненти, модель даних, API.
2. [docs/isd.md](docs/isd.md): середовища, CI/CD, резервне копіювання.
3. Рішення та причини: [docs/architecture/adr/](docs/architecture/adr/).
4. Запустіть систему (швидкий старт) і тести, відкрийте `routes.py` та `models.py`.
5. Правила підтримки: [docs/maintenance.md](docs/maintenance.md) (зміна коду = зміна документації).

## Документація

| Документ | Для кого |
|---|---|
| [SDD](docs/sdd.md) | розробники, QA |
| [ISD](docs/isd.md) | DevOps |
| [ADR](docs/architecture/adr/) | розробники, архітектори |
| [Матриця аудиторій](docs/audience-matrix.md) | усі |
| [Регламент](docs/maintenance.md) | власники документів |

## Quality and security checks

- Complexity: `radon cc -s -a .` and `flake8 --select=CCR --max-cognitive-complexity=15 routes.py`
- Tests: `pytest tests/ -v`
- SCA: `pip-audit -r requirements.txt`
- Secrets: `pre-commit install` once, then every commit runs `gitleaks protect --staged`. Full history: `gitleaks detect --source . --redact -v`
- Copy `.env.example` to `.env` and fill in real values locally (`.env` is git-ignored)
