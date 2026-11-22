# ISD: Infrastructure Specification Document (Farm-association)

Статус: актуальний · Власник: Denys Brenkach · Остання перевірка: 2026-11-22 · Цикл перегляду: 90 днів
Пов'язані документи: [SDD](sdd.md) · [ADR-0001](architecture/adr/0001-postgresql-as-data-store.md) · [README](../README.md)

## 1. Огляд
Контейнерне розгортання через Docker Compose: два сервіси (`db`, `web`). Окремі compose-файли для статичного аналізу (`docker-compose.sonar.yml`) і метрик (`docker-compose.metrics.yml`).

## 2. Топологія розгортання
| Сервіс | Образ / збірка | Контейнер | Порт хоста → контейнера | Залежності |
|---|---|---|---|---|
| `db` | `postgres:15-alpine` | `farm_db` | 5433 → 5432 | том `postgres_data` |
| `web` | `build: .` (`python:3.12-slim`, користувач `appuser`, не root) | `farm_web` | 5001 → 5000 | `depends_on: db` |

Порядок запуску: `db` стартує першим, потім `web` (`depends_on` без перевірки готовності БД). Застосунок при старті виконує `db.create_all()` і створює користувача `admin`. Опис компонентів, що працюють усередині `web`: див. [SDD §3](sdd.md#3-компоненти-веб-застосунку).

## 3. Середовища та змінні оточення
| Середовище | Де працює | Як налаштовується |
|---|---|---|
| dev | локальний Docker Compose | файл `.env` (поза Git), шаблон `.env.example` |
| test | GitHub Actions (`ubuntu-latest`) | pytest без реальної БД, секрети з GitHub Secrets |
| production | цільове: контейнерний хост із тією ж compose-топологією | змінні з менеджера секретів, не з файлу в репозиторії |

Змінні (значення не наводяться): `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DATABASE`, `SECRET_KEY`, `ADMIN_PASSWORD`, `FLASK_ENV`, `GITHUB_TOKEN`. У dev-compose змінні БД задано прямо у файлі, для production це заборонено (ризик R2).

## 4. Збірка образу
Версії залежностей зафіксовано з хешами (`pip install --require-hashes -r requirements.txt`), копіюються лише файли застосунку, `templates/` і `static/`; процес працює від `appuser`.

## 5. Сховища даних
PostgreSQL 15, база `farm_db`, постійний том `postgres_data` (`/var/lib/postgresql/data`). Таблиці описані в [SDD §4](sdd.md#4-модель-даних). Обґрунтування вибору: [ADR-0001](architecture/adr/0001-postgresql-as-data-store.md).

## 6. CI/CD конвеєр
| Workflow | Тригер | Стадії / Quality Gates |
|---|---|---|
| `ci.yml` (Flask CI) | push у `main`, `lab3`; pull request у `main` | `build-test`: встановлення з хешами → `pytest tests/ -v` → `pip-audit` (падіння при вразливостях); `secret-scan`: Gitleaks по повній історії |
| `complexity-report.yml` | кожен push і pull request | Lizard, Radon, Churn Rate, матриця Hotspots, артефакт `complexity-report` |
| локальний `git-hooks/pre-commit` | кожен коміт | блокує коміт, якщо функція має CC > 10 |
| `.pre-commit-config.yaml` | кожен коміт | `gitleaks protect --staged` |

## 7. Моніторинг і логування
Логи застосунку проходять через `privacy_logging`: маскування PII, correlation ID (`X-Correlation-ID`). Журнал `audit_events` зберігає факти операцій без персональних даних. Перегляд: `docker compose logs web`. Healthcheck не налаштовано (ризик R3).

## 8. Резервне копіювання та відновлення
| Показник | Цільове значення |
|---|---|
| RPO (допустима втрата даних) | 24 години |
| RTO (допустимий час відновлення) | 4 години |

Процедура: щоденний `docker exec farm_db pg_dump -U $PG_USER farm_db > backup.sql`; відновлення: `docker compose up -d db`, потім `psql < backup.sql`, потім `docker compose up -d web`. Автоматичний запуск резервного копіювання поки не налаштовано (ризик R1).

## 9. Відкат релізу
`git checkout <попередній-тег>` → `docker compose up -d --build web`. Схема БД керується `create_all()` без міграцій, тому зміни схеми відкату не підлягають (ризик R4).

## 10. Реєстр ризиків
R1: немає автоматичного бекапу · R2: пароль БД літералом у dev-compose · R3: немає healthcheck · R4: немає міграцій схеми.
