"""Сервіси сповіщень (Лаб. 8, Завдання 3): композиція замість успадкування (Replace Inheritance with Composition).

CampaignNotifier  --містить-->  ConsentAwareNotifier  --містить-->  BaseNotifier
Жодного ключового слова наслідування: попередній «предок» став приватним полем _inner, який
передається через конструктор (Dependency Injection), а нащадок лише делегує йому виклики.
Сигнатуру BaseNotifier.build_message знає лише один виклик у ConsentAwareNotifier.send().
"""
from __future__ import annotations


class BaseNotifier:
    """Рівень 1: базова доставка повідомлень."""

    channel = "generic"

    def __init__(self, limit: int = 200):
        self._limit = limit
        self._sent: list = []

    def normalize(self, text: str) -> str:
        return " ".join(text.split())

    def validate(self, text: str) -> bool:
        return bool(text) and len(text) <= self._limit

    def build_message(self, login: str, text: str, *, channel: str) -> dict:
        return {"to": login, "text": text, "channel": channel}

    def render(self, message: dict) -> str:
        return f"[{message['channel']}] {message['to']}: {message['text']}"

    def deliver(self, message: dict) -> None:
        self._sent.append(message)

    def send(self, login: str, text: str) -> dict:
        text = self.normalize(text)
        if not self.validate(text):
            return {"ok": False, "reason": "INVALID"}
        message = self.build_message(login, text, channel=self.channel)
        self.deliver(message)
        return {"ok": True, "rendered": self.render(message)}

    def history(self) -> list:
        return list(self._sent)

    def count(self) -> int:
        return len(self._sent)

    def clear(self) -> None:
        self._sent.clear()

    def stats(self) -> dict:
        return {"sent": len(self._sent), "channel": self.channel}

    def audit_line(self, message: dict) -> str:
        return f"SENT to={message['to']} ch={message['channel']}"


class ConsentAwareNotifier:
    """Рівень 2 (композиція): надсилає лише за згодою та поважає список блокувань."""

    def __init__(self, inner: BaseNotifier, consents: dict | None = None):
        self._inner = inner
        self._consents = consents if consents is not None else {}
        self._blocked: set = set()

    def send(self, login: str, text: str) -> dict:
        if login in self._blocked:
            return {"ok": False, "reason": "BLOCKED"}
        if not self.check_consent(login):
            return {"ok": False, "reason": "NO_CONSENT"}
        text = self._inner.normalize(text)
        if not (self._inner.validate(text) and "STOP" not in text.upper()):
            return {"ok": False, "reason": "INVALID"}
        message = self._inner.build_message(login, text, channel=self._inner.channel)
        message["consent"] = self.check_consent(login)
        self._inner.deliver(message)
        suffix = " (consented)" if message["consent"] else " (no consent)"
        return {"ok": True, "rendered": self._inner.render(message) + suffix}

    def check_consent(self, login: str) -> bool:
        return bool(self._consents.get(login))

    def consent_state(self) -> dict:
        return dict(self._consents)

    def block(self, login: str) -> None:
        self._blocked.add(login)

    def unblock(self, login: str) -> None:
        self._blocked.discard(login)

    def list_blocked(self) -> list:
        return sorted(self._blocked)

    def history(self) -> list:
        return self._inner.history()

    def stats(self) -> dict:
        return self._inner.stats()

    def audit_line(self, message: dict) -> str:
        return self._inner.audit_line(message)


class CampaignNotifier:
    """Рівень 3 (композиція): кампанії, шаблони та відкладена розсилка."""

    def __init__(self, inner: ConsentAwareNotifier, templates: dict | None = None):
        self._inner = inner
        self._templates = dict(templates or {"default": "{text}"})
        self._scheduled: list = []
        self._cancelled: set = set()

    def send(self, login: str, text: str) -> dict:
        result = self._inner.send(login, " ".join(text.split()).strip().capitalize())
        if result["ok"]:
            result["rendered"] = result["rendered"].upper()
        result["campaign"] = True
        return result

    def stats(self) -> dict:
        data = self._inner.stats()
        data["scheduled"] = len(self._scheduled)
        return data

    def audit_line(self, message: dict) -> str:
        return self._inner.audit_line(message) + " campaign=1"

    def history(self) -> list:
        return self._inner.history()

    def set_template(self, name: str, template: str) -> None:
        self._templates[name] = template

    def templates(self) -> dict:
        return dict(self._templates)

    def schedule(self, login: str, text: str, when: str) -> int:
        self._scheduled.append((when, login, text))
        return len(self._scheduled)

    def cancel(self, index: int) -> None:
        self._cancelled.add(index)

    def bulk_send(self, logins: list, text: str, template: str = "default") -> list:
        return [self.send(login, self._templates[template].format(text=text)) for login in logins]

    def campaign_report(self) -> dict:
        results = [self.send(login, text) for _when, login, text in self._scheduled]
        return {"planned": len(self._scheduled), "cancelled": len(self._cancelled),
                "delivered": sum(1 for r in results if r["ok"])}
