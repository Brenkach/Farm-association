"""Лаб. 8, Завдання 3: поведінка ієрархії сповіщень (наслідування). Дані синтетичні."""
import pytest

from notifiers import BaseNotifier, CampaignNotifier, ConsentAwareNotifier

ALICE, BOB = "alice_test", "bob_test"
CONSENTS = {ALICE: True, BOB: False}


# ----------------------------------------------------------------------------- рівень 1: BaseNotifier
def test_base_send_delivers_and_renders():
    n = BaseNotifier()
    assert n.send(ALICE, "Hello   world") == {"ok": True, "rendered": "[generic] alice_test: Hello world"}
    assert n.count() == 1 and n.history()[0]["text"] == "Hello world"


def test_base_rejects_empty_and_too_long_messages():
    n = BaseNotifier(limit=5)
    assert n.send(ALICE, "")["reason"] == "INVALID"
    assert n.send(ALICE, "toolongtext")["reason"] == "INVALID"


def test_base_stats_and_clear():
    n = BaseNotifier()
    n.send(ALICE, "a")
    assert n.stats() == {"sent": 1, "channel": "generic"}
    n.clear()
    assert n.count() == 0


def test_base_audit_line():
    assert BaseNotifier().audit_line({"to": ALICE, "channel": "generic"}) == "SENT to=alice_test ch=generic"


# ----------------------------------------------------------------------------- рівень 2: ConsentAwareNotifier
def test_consent_aware_sends_with_consent_and_marks_rendering():
    n = ConsentAwareNotifier(CONSENTS)
    result = n.send(ALICE, "Hi")
    assert result["ok"] and result["rendered"].endswith("(consented)")
    assert n.history()[0]["consent"] is True


def test_consent_aware_refuses_without_consent():
    assert ConsentAwareNotifier(CONSENTS).send(BOB, "Hi") == {"ok": False, "reason": "NO_CONSENT"}


def test_consent_aware_block_and_unblock():
    n = ConsentAwareNotifier(CONSENTS)
    n.block(ALICE)
    assert n.send(ALICE, "Hi")["reason"] == "BLOCKED" and n.list_blocked() == [ALICE]
    n.unblock(ALICE)
    assert n.send(ALICE, "Hi")["ok"] is True


def test_consent_aware_rejects_stop_word():
    assert ConsentAwareNotifier(CONSENTS).send(ALICE, "please stop now")["reason"] == "INVALID"


def test_consent_state_is_a_copy():
    n = ConsentAwareNotifier(CONSENTS)
    n.consent_state()[ALICE] = False
    assert n.check_consent(ALICE) is True


# ----------------------------------------------------------------------------- рівень 3: CampaignNotifier
def test_campaign_normalizes_and_uppercases_rendering():
    result = CampaignNotifier(CONSENTS).send(ALICE, "  big   SALE ")
    assert result["ok"] and result["campaign"] is True
    assert result["rendered"] == "[GENERIC] ALICE_TEST: BIG SALE (CONSENTED)"


def test_campaign_inherits_consent_rules():
    assert CampaignNotifier(CONSENTS).send(BOB, "Sale")["reason"] == "NO_CONSENT"


def test_campaign_stats_include_scheduled_count():
    n = CampaignNotifier(CONSENTS)
    n.schedule(ALICE, "Later", "2026-12-01")
    assert n.stats() == {"sent": 0, "channel": "generic", "scheduled": 1}


def test_campaign_audit_line_has_campaign_flag():
    assert CampaignNotifier().audit_line({"to": ALICE, "channel": "generic"}).endswith("campaign=1")


def test_campaign_bulk_send_uses_templates():
    n = CampaignNotifier(CONSENTS, templates={"default": "{text}", "promo": "PROMO {text}"})
    results = n.bulk_send([ALICE, BOB], "offer", template="promo")
    assert [r["ok"] for r in results] == [True, False]
    assert n.history()[0]["text"] == "Promo offer"


def test_campaign_templates_can_be_extended():
    n = CampaignNotifier()
    n.set_template("x", "X {text}")
    assert "x" in n.templates()


def test_campaign_report_delivers_scheduled_messages():
    n = CampaignNotifier(CONSENTS)
    n.schedule(ALICE, "One", "d1")
    n.schedule(BOB, "Two", "d2")
    n.cancel(1)
    assert n.campaign_report() == {"planned": 2, "cancelled": 1, "delivered": 1}
