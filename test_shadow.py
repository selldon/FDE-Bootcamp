"""Fast tests of the shadow store: no network, no database."""
import re
from datetime import UTC, datetime, timedelta

from psycopg import sql

import shadow
from shadow import FakeShadowStore

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


def chat(number, minutes=0, **extra):
    return {"number": number, "opened_at": T0 + timedelta(minutes=minutes), "opened_for": "maya.ross@example.com",
            "market": "US", "message": "Where is DS-20417?", "intent": "order_status", "action": "answered",
            "answer": "It ships Monday.", "would_have": {"offer": None}, "state": "work_in_progress",
            "answered_at": T0 + timedelta(minutes=minutes, seconds=5), **extra}


def test_saves_once_per_number():
    store = FakeShadowStore()
    assert store.save(chat("INT001")) is True
    assert store.save(chat("INT001", answer="a different answer")) is False
    assert len(store.rows) == 1 and store.rows["INT001"]["answer"] == "It ships Monday."


def test_watermark_is_the_newest_opened_at():
    store = FakeShadowStore()
    assert store.watermark() is None
    store.save(chat("INT002", minutes=5))
    store.save(chat("INT001", minutes=1))
    assert store.watermark() == T0 + timedelta(minutes=5)


def test_close_only_fills_an_empty_agent_reply():
    store = FakeShadowStore()
    store.save(chat("INT001"))
    assert store.open_numbers() == ["INT001"]
    assert store.close("INT001", "Sent today.") is True
    assert store.close("INT001", "Something else.") is False
    assert store.rows["INT001"]["agent_reply"] == "Sent today." and store.rows["INT001"]["state"] == "closed_complete"
    assert store.close("INT999", "no such chat") is False
    assert store.open_numbers() == []


def test_last_is_newest_first_and_limited():
    store = FakeShadowStore()
    for i in range(25):
        store.save(chat(f"INT{i:03}", minutes=i))
    rows = store.last(20)
    assert len(rows) == 20 and rows[0]["number"] == "INT024" and rows[-1]["number"] == "INT005"


def test_the_table_holds_only_the_chat():
    # no session id, customer hash or other customer data: the columns are exactly these
    assert shadow.FIELDS == ("number", "opened_at", "opened_for", "market", "message", "intent", "action", "answer",
                             "would_have", "state", "agent_reply", "answered_at")
    [statement] = shadow.tables("shadow_chats")
    text = statement.as_string(None) if isinstance(statement, sql.Composable) else str(statement)
    assert set(re.findall(r"^\s*(?:\(|)\s*(\w+) (?:text|timestamptz|jsonb)", text.replace(", ", ",\n"), re.MULTILINE)) == set(shadow.FIELDS)
    row = FakeShadowStore()
    row.save(chat("INT001", session_id="s1", customer_hash="abc"))
    assert set(row.rows["INT001"]) == set(shadow.FIELDS)
