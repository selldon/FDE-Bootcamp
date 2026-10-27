"""Fast tests of the go-live API: a FakeGoLiveStore behind the real routes, no database, no model."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app as chat_app
from golive import ASSISTANT, CONTROL, FakeGoLiveStore

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
_ids = iter(range(10**6))


def chat(group, day=1, **extra):
    n = next(_ids)
    return {"visitor_id": f"v{n}", "chat_id": f"A{n}", "group_name": group, "intent": "order_status", "outcome": "resolved",
            "simulated": True, "sim_day": day, "created_at": T0 + timedelta(days=day), "rating": 4, **extra}


@pytest.fixture
def store():
    s = FakeGoLiveStore()
    s.create_tables()
    for row in [chat(ASSISTANT) for _ in range(5)] + [chat(CONTROL) for _ in range(5)]:
        s.save_chat(row)
    return s


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(chat_app, "golive_store", lambda: store)
    return TestClient(chat_app.app)


def test_the_page_data_has_both_groups_the_difference_the_lines_and_the_switch(client):
    body = client.get("/api/golive").json()
    assert body["total"] == 10 and body["simulated"] == 10
    window = body["window"]
    assert window["assistant"]["chats"] == 5 and window["control"]["chats"] == 5
    assert {"n_assistant", "n_control", "resolved", "unanswered", "rating"} <= set(window["difference"])
    assert set(body["lines"]["window"]) == {"confidently_wrong", "hand_off", "unanswered", "rating"}
    assert body["lines"]["two_weeks"]["status"] == "not enough yet"  # one day of chats
    assert body["lines"]["day"]["alert"] is False
    assert body["settings"]["on"] is False


def test_an_empty_store_gives_not_enough_yet_not_an_error(monkeypatch):
    empty = FakeGoLiveStore()
    empty.create_tables()
    monkeypatch.setattr(chat_app, "golive_store", lambda: empty)
    r = TestClient(chat_app.app).get("/api/golive")
    assert r.status_code == 200 and r.json()["total"] == 0
    assert r.json()["lines"]["two_weeks"]["status"] == "not enough yet"


def test_a_wrong_answer_on_the_latest_day_raises_the_alert(client, store):
    store.save_chat(chat(ASSISTANT, day=2, confidently_wrong=True))
    body = client.get("/api/golive").json()
    assert body["lines"]["day"]["alert"] is True and body["lines"]["alert_days"] == [2]


def test_the_switch_changes_what_the_next_read_sees(client, store):
    assert client.post("/api/golive/switch", json={"on": True}).json()["on"] is True
    assert store.settings()["on"] is True and client.get("/api/golive/switch").json()["on"] is True
    assert client.post("/api/golive/switch", json={"on": False}).json()["on"] is False
    assert client.get("/api/golive").json()["settings"]["on"] is False


def test_the_switch_keeps_what_is_left_out_and_refuses_a_bad_share(client):
    body = client.post("/api/golive/switch", json={"on": True, "share": 0.25}).json()
    assert body["share"] == 0.25 and body["intents"] == ["order_status"]
    assert client.post("/api/golive/switch", json={"share": 2}).status_code == 422
    assert client.get("/api/golive/switch").json()["share"] == 0.25
