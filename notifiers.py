"""Ієрархія сервісів сповіщень (Лаб. 8, Завдання 3): три рівні успадкування.

BaseNotifier  ->  ConsentAwareNotifier  ->  CampaignNotifier
Нащадки перевизначають методи предків, частково переписуючи їхню логіку, тому будь-яка зміна
в базовому класі «простріляє» усю ланцюжок (Inheritance Hell).
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


class ConsentAwareNotifier(BaseNotifier):
    """Рівень 2: надсилає лише за згодою та поважає список блокувань."""

    def __init__(self, consents: dict | None = None, limit: int = 200):
        super().__init__(limit)
        self._consents = consents if consents is not None else {}
        self._blocked: set = set()

    # --- перевизначені методи предка ---
    def validate(self, text: str) -> bool:
        # логіку предка переписано повністю, замість виклику super()
        return bool(text) and len(text) <= self._limit and "STOP" not in text.upper()

    def build_message(self, login: str, text: str) -> dict:
        message = super().build_message(login, text)
        message["consent"] = self.check_consent(login)
        return message

    def render(self, message: dict) -> str:
        return super().render(message) + (" (consented)" if message.get("consent") else " (no consent)")

    def send(self, login: str, text: str) -> dict:
        if login in self._blocked:
            return {"ok": False, "reason": "BLOCKED"}
        if not self.check_consent(login):
            return {"ok": False, "reason": "NO_CONSENT"}
        return super().send(login, text)

    # --- нові методи ---
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


class CampaignNotifier(ConsentAwareNotifier):
    """Рівень 3: кампанії, шаблони та відкладена розсилка."""

    def __init__(self, consents: dict | None = None, limit: int = 200, templates: dict | None = None):
        super().__init__(consents, limit)
        self._templates = dict(templates or {"default": "{text}"})
        self._scheduled: list = []
        self._cancelled: set = set()

    # --- перевизначені методи предків ---
    def normalize(self, text: str) -> str:
        # логіку предка переписано повністю, замість виклику super()
        return " ".join(text.split()).strip().capitalize()

    def render(self, message: dict) -> str:
        return super().render(message).upper()

    def send(self, login: str, text: str) -> dict:
        result = super().send(login, text)
        result["campaign"] = True
        return result

    def stats(self) -> dict:
        data = super().stats()
        data["scheduled"] = len(self._scheduled)
        return data

    def audit_line(self, message: dict) -> str:
        return super().audit_line(message) + " campaign=1"

    # --- нові методи ---
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
