"""Лаб. 7: Value Object ExportRequest незмінний і містить правила доступу (без БД)."""
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from personal_data import ExportRequest


def make(actor_login="alice", role="farmer", subject="alice"):
    return ExportRequest(actor=SimpleNamespace(login=actor_login, access_right=role), subject_login=subject)


def test_value_object_is_immutable():
    req = make()
    with pytest.raises(FrozenInstanceError):
        req.subject_login = "mallory"          # спроба «перезаписати» субʼєкта
    with pytest.raises(FrozenInstanceError):
        req.actor = SimpleNamespace(login="x", access_right="superuser")


@pytest.mark.parametrize("actor_login, role, subject, is_self, is_privileged, allowed", [
    ("alice", "farmer", "alice", True, False, True),         # власні дані
    ("alice", "farmer", "bob", False, False, False),         # чужі дані без повноважень
    ("root", "superuser", "bob", False, True, True),         # привілейована роль
    ("root", "superuser", "root", True, True, True),
])
def test_access_rules_live_inside_the_object(actor_login, role, subject, is_self, is_privileged, allowed):
    req = make(actor_login, role, subject)
    assert (req.is_self, req.is_privileged, req.allowed) == (is_self, is_privileged, allowed)


def test_find_subject_returns_actor_for_self_request():
    req = make("alice", "farmer", "alice")
    assert req.find_subject() is req.actor


def test_equal_requests_are_equal_values():
    assert make() == make()                      # Value Object: рівність за значенням
