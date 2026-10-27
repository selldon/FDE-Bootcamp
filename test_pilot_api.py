"""Fast tests of the pilot API: a FakeShadowStore behind the real routes, no database, no model."""
import json
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app as chat_app
from shadow import FakeShadowStore

EMAIL = "maya.ross@example.com"
CARD = "4111 1111 1111 1111"
T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


def chat(number, **extra):
    row = {"number": number, "opened_at": T0, "opened_for": EMAIL, "market": "US", "message": "Where is DS-1?",
           "intent": "order_status", "action": "give_status", "answer": "Monday.", "agent_reply": "It ships Monday.",
           "answered_at": T0, "input_tokens": 1000, "output_tokens": 100}
    return row | extra


@pytest.fixture
def store():
    s = FakeShadowStore()
    for row in (chat("INT1"), chat("INT2", action="hand_off"), chat("INT3", agent_reply=None)):
        s.save(row)
    return s


@pytest.fixture
def client(store):
    chat_app.app.dependency_overrides[chat_app.pilot_store] = lambda: store
    yield TestClient(chat_app.app)
    chat_app.app.dependency_overrides.clear()


def test_numbers_have_the_total_the_breakdowns_and_three_sentences(client):
    body = client.get("/api/pilot").json()
    assert body["total"] == 3 and body["resolved"] == 2
    for name in ("days", "markets", "actions", "intents"):
        assert sum(r["chats"] for r in body[name]) == 3
    assert len(body["sentences"]) == 3 and body["baseline"]["person_cost"] == 7.0
    assert body["checked"]["sample"] == 0


def test_the_sample_is_unmarked_chats_with_an_agent_reply(client):
    sample = client.get("/api/pilot/sample").json()
    assert {c["number"] for c in sample} == {"INT1", "INT2"}
    assert {"number", "message", "answer", "agent_reply", "action"} <= set(sample[0])


def test_a_mark_is_stored_returned_and_leaves_the_sample(client, store):
    r = client.post("/api/pilot/mark", json={"number": "INT1", "marker": " Lena ", "verdict": "wrong", "sounded_sure": True})
    assert r.status_code == 200
    assert r.json()["marker"] == "Lena" and r.json()["verdict"] == "wrong" and r.json()["sounded_sure"] is True
    assert [m["marker"] for m in store.marks("INT1")] == ["Lena"]
    assert {c["number"] for c in client.get("/api/pilot/sample").json()} == {"INT2"}
    assert client.get("/api/pilot").json()["checked"]["sample"] == 1


def test_a_bad_mark_is_a_422_and_stores_nothing(client, store):
    for body in ({"number": "INT1", "marker": "Lena", "verdict": "great"},
                 {"number": "INT1", "marker": "  ", "verdict": "same"},
                 {"number": "INT1", "marker": "Lena", "verdict": "same", "sounded_sure": True},
                 {"number": "NOPE", "marker": "Lena", "verdict": "same"}):
        assert client.post("/api/pilot/mark", json=body).status_code == 422
    assert store.marks() == []


def test_no_email_in_any_payload(client):
    client.post("/api/pilot/mark", json={"number": "INT2", "marker": "Marco", "verdict": "same"})
    payloads = [client.get("/api/pilot").text, client.get("/api/pilot/sample").text,
                client.post("/api/pilot/mark", json={"number": "INT1", "marker": "Lena", "verdict": "better"}).text]
    for text in payloads:
        assert EMAIL not in text and not re.search(r"\S+@\S+\.\w+", text) and "opened_for" not in text


def test_a_card_number_in_an_old_row_comes_out_masked(client, store):
    store.save(chat("INT9", message=f"my card is {CARD}", answer=f"I see {CARD}", agent_reply=f"card {CARD}"))
    text = client.get("/api/pilot/sample").text
    assert "4111" not in text and json.loads(text)
    row = next(c for c in client.get("/api/pilot/sample").json() if c["number"] == "INT9")
    assert all("[card number removed]" in row[f] for f in ("message", "answer", "agent_reply"))
