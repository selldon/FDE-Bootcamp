"""Card numbers are masked before anything else sees a chat message (B21, IT24)."""
import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import masking
from conftest import reply, text
from masking import REMOVED, mask_cards

client = TestClient(app_module.app)
HARD = {x["id"]: x["message"] for x in json.loads(Path("data/hard_messages.json").read_text())}
INTENT = json.dumps({"summary": "card", "intent": "order_status", "order_number": None,
                     "needs_human": False, "damaged": False, "language": "en"})


@pytest.mark.parametrize("key, digits", [
    ("X07", "4111 1111 1111 1111"), ("X08", "5500005555555559"),
    ("X09", "4012-8888-8888-1881"), ("X10", "378282246310005")])
def test_hard_card_messages_lose_the_number(key, digits):
    out = mask_cards(HARD[key])
    assert digits not in out and REMOVED in out
    assert not any(ch.isdigit() for ch in out.replace("DS-20498", "").replace("DS-20447", "").replace("0005", ""))


def test_rest_of_message_is_kept():
    assert mask_cards("Card 4111 1111 1111 1111 for DS-20498, thanks") == f"Card {REMOVED} for DS-20498, thanks"


def test_luhn_invalid_number_and_order_number_are_kept():
    for kept in ("4111 1111 1111 1112", "1234567890123456", "Order DS-20377 is late", "call 0207 946 0958"):
        assert mask_cards(kept) == kept


def test_two_cards_in_one_message():
    assert mask_cards("4111111111111111 and 5500005555555559") == f"{REMOVED} and {REMOVED}"


def test_digits_split_by_text_are_not_joined():
    split = "4111 1111 card 1111 1111"
    assert mask_cards(split) == split


def test_too_short_or_too_long_runs_are_kept():
    for kept in ("424242424242", "42424242424242424242"):
        assert mask_cards(kept) == kept


@pytest.mark.parametrize("typed", [
    "4111.1111.1111.1111", "4111  1111 1111 1111", "4111/1111/1111/1111", "4111\u00a01111\u00a01111\u00a01111",
    "4111 - 1111 - 1111 - 1111"])
def test_other_separators_do_not_hide_a_card(typed):
    assert mask_cards(f"card {typed} thanks") == f"card {REMOVED} thanks"


@pytest.mark.parametrize("typed, rest", [
    ("4111 1111 1111 1111 123", " 123"), ("4111111111111111 123", " 123"), ("123 4111 1111 1111 1111", "123 ")])
def test_a_card_next_to_a_cvv_is_still_removed(typed, rest):
    out = mask_cards(typed)
    assert REMOVED in out and "4111" not in out
    assert out.replace(REMOVED, "") == rest


def test_two_cards_in_one_run_of_digits():
    assert mask_cards("4111111111111111 5500005555555559") == f"{REMOVED} {REMOVED}"


def test_module_does_no_io():
    tree = ast.parse(Path(masking.__file__).read_text())
    imported = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
    assert imported <= {"re"}
    assert not any(isinstance(n, ast.Call) and getattr(n.func, "id", "") in {"open", "print"} for n in ast.walk(tree))


@pytest.fixture(autouse=True)
def fresh_sessions(monkeypatch):
    monkeypatch.setattr(app_module, "SESSIONS", {})


def test_model_inputs_and_history_never_carry_the_digits(fake_model):
    model = fake_model(reply(text(INTENT)), reply(text("ok")))
    out = client.post("/chat", json={"message": HARD["X07"]}).json()
    assert "4111" not in json.dumps(model.calls)
    assert REMOVED in json.dumps(model.calls)
    assert "4111" not in json.dumps(app_module.SESSIONS[out["session_id"]]["history"])


def test_case_carries_only_the_masked_text(monkeypatch, fake_model, fake_systems):
    monkeypatch.setattr(app_module, "classify", lambda message, usage=None: {
        "summary": "s", "intent": "order_status", "order_number": None,
        "needs_human": True, "damaged": False, "language": "en"})
    fake_model()
    client.post("/chat", json={"message": HARD["X08"]})
    [case] = fake_systems.snow.cases
    assert "5500005555555559" not in json.dumps(case)
    assert REMOVED in case["u_conversation"]


def test_classify_gets_the_masked_message(monkeypatch, fake_model):
    seen = []

    def spy(message, usage=None):
        seen.append(message)
        return {"summary": "s", "intent": "other", "order_number": None,
                "needs_human": False, "damaged": False, "language": "en"}
    monkeypatch.setattr(app_module, "classify", spy)
    fake_model(reply(text("ok")))
    client.post("/chat", json={"message": HARD["X10"]})
    assert seen == [f"Card {REMOVED} ends in 0005. Where is my order DS-20447?"]
