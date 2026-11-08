"""Журнал аудиту подій приватності (Лаб. 8): сторонній клас, від якого залежить God Object.

Пише privacy-safe записи AuditEvent (псевдонім суб'єкта, тип події, результат): без PII.
"""
from __future__ import annotations

from anonymization import AuditEvent
from extensions import db
from personal_data import subject_ref


class AuditTrail:
    """Єдина точка запису подій аудиту в базу."""

    def record(self, subject: str, event_type: str, result: str, *, actor: str) -> None:
        db.session.add(AuditEvent(event_type=event_type, subject_ref=subject_ref(subject),
                                  actor_ref=subject_ref(actor), result=result))
        db.session.commit()
