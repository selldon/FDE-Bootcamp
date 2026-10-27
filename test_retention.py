"""Retention and erasure (B23, IT26): fast tests with FakeTraces, a fake clock and a temp outbox."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app as app_module
import retention
import traces
import verify
from conftest import reply, text

MAYA = "maya.ross@example.com"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("TRACE_HMAC_KEY", "test-key-one")


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    path = tmp_path / "outbox.jsonl"
    monkeypatch.setattr(verify, "_default", verify.Verifier(outbox=str(path)))
    return path


@pytest.fixture(autouse=True)
def sessions(monkeypatch):
    monkeypatch.setattr(app_module, "SESSIONS", {})
    return app_module.SESSIONS


client = TestClient(app_module.app)


def row(days_old, session_id=None, customer=None):
    return {"at": NOW - timedelta(days=days_old), "session_id": session_id, "customer_hash": customer,
            "model": "m", "prompt": "p", "reply": "r", "input_tokens": 1, "output_tokens": 1,
            "cost": None, "kind": "ask"}


def code_for(outbox):
    return json.loads(outbox.read_text().splitlines()[-1])["code"]


def verified_session(outbox):
    sid = client.post("/verify/start", json={"email": MAYA}).json()["session_id"]
    client.post("/verify/check", json={"session_id": sid, "email": MAYA, "code": code_for(outbox)})
    return sid


def test_89_days_kept_91_deleted_and_exactly_90_kept_by_the_written_rule(fake_traces):
    for days in (89, 90, 91):
        fake_traces.add(row(days))
    assert retention.purge(now=NOW) == 1
    assert sorted((NOW - r["at"]).days for r in fake_traces.rows) == [89, 90]
    retention.purge(now=NOW + timedelta(seconds=1))  # one second later the 90-day trace is over the limit
    assert sorted((NOW - r["at"]).days for r in fake_traces.rows) == [89]


def test_purge_uses_the_given_clock_and_days(fake_traces):
    fake_traces.add(row(10))
    assert retention.purge(older_than_days=5, now=NOW) == 1 and fake_traces.rows == []


def test_the_hash_is_hmac_not_plain_sha256(monkeypatch):
    first = traces.customer_hash(MAYA)
    assert traces.customer_hash("  Maya.Ross@Example.com ") == first
    assert first != hashlib.sha256(MAYA.encode()).hexdigest()
    monkeypatch.setenv("TRACE_HMAC_KEY", "another-key")
    assert traces.customer_hash(MAYA) != first
    assert MAYA not in first


def test_verifying_fills_the_earlier_rows_and_later_calls_carry_the_hash(outbox, fake_traces, fake_model):
    sid = client.post("/verify/start", json={"email": MAYA}).json()["session_id"]
    fake_traces.add(row(0, session_id=sid))
    fake_traces.add(row(0, session_id="other"))
    client.post("/verify/check", json={"session_id": sid, "email": MAYA, "code": code_for(outbox)})
    mine, other = fake_traces.rows
    assert mine["customer_hash"] == traces.customer_hash(MAYA) and other["customer_hash"] is None
    intent = json.dumps({"summary": "s", "intent": "other", "order_number": None,
                         "needs_human": False, "damaged": False, "language": "en"})
    fake_model(reply(text(intent)), reply(text("hi")))
    client.post("/chat", json={"session_id": sid, "message": "hello"})
    assert [r["customer_hash"] for r in fake_traces.rows[2:]] == [traces.customer_hash(MAYA)] * 2


def test_a_wrong_code_does_not_fill_the_hash(outbox, fake_traces):
    sid = client.post("/verify/start", json={"email": MAYA}).json()["session_id"]
    fake_traces.add(row(0, session_id=sid))
    client.post("/verify/check", json={"session_id": sid, "email": MAYA, "code": "000000"})
    assert fake_traces.rows[0]["customer_hash"] is None


def test_erasure_deletes_only_her_rows_and_logs_no_personal_data(outbox, fake_traces, sessions):
    sid = verified_session(outbox)
    mine = traces.customer_hash(MAYA)
    fake_traces.add(row(1, session_id=sid, customer=mine))
    fake_traces.add(row(1, session_id="s-old", customer=mine))
    fake_traces.add(row(1, session_id="s-other", customer="someone-else"))
    fake_traces.add(row(1, session_id=None))
    sessions["s-b"] = {"customer": "ben@example.com", "history": []}
    client.post("/erase/start", json={"email": MAYA})
    out = client.post("/erase/check", json={"session_id": sid, "email": MAYA, "code": code_for(outbox)}).json()
    assert out["erased"] is True and "ServiceNow" not in out["reply"] and "support team" in out["reply"]
    assert [r["session_id"] for r in fake_traces.rows] == ["s-other", None]
    assert sid not in sessions and "s-b" in sessions
    [entry] = fake_traces.erasures
    assert set(entry) == {"at", "rows_deleted"} and entry["rows_deleted"] == 2
    assert MAYA not in str(entry) and mine not in str(entry)


def test_erasure_also_finds_rows_by_her_session_ids(outbox, fake_traces, sessions):
    sid = verified_session(outbox)
    fake_traces.add(row(1, session_id=sid))  # written after verification by some path that left no hash
    client.post("/erase/start", json={"email": MAYA})
    client.post("/erase/check", json={"email": MAYA, "code": code_for(outbox)})
    assert fake_traces.rows == []


def test_a_wrong_code_or_no_code_deletes_nothing(outbox, fake_traces, sessions):
    sid = verified_session(outbox)
    fake_traces.add(row(1, session_id=sid, customer=traces.customer_hash(MAYA)))
    client.post("/erase/start", json={"email": MAYA})
    out = client.post("/erase/check", json={"session_id": sid, "email": MAYA, "code": "000000"}).json()
    assert out["erased"] is False
    nobody = client.post("/erase/check", json={"email": "nobody@example.com", "code": "123456"}).json()
    assert nobody["erased"] is False
    assert len(fake_traces.rows) == 1 and sid in sessions and fake_traces.erasures == []


def test_erasure_twice_is_safe(outbox, fake_traces):
    sid = verified_session(outbox)
    fake_traces.add(row(1, session_id=sid, customer=traces.customer_hash(MAYA)))
    for expected in (1, 0):
        client.post("/erase/start", json={"email": MAYA})
        assert client.post("/erase/check", json={"email": MAYA, "code": code_for(outbox)}).json()["erased"]
        assert fake_traces.erasures[-1]["rows_deleted"] == expected
    assert fake_traces.rows == []


def test_after_a_restart_her_rows_are_still_found_by_hash(outbox, fake_traces, sessions):
    fake_traces.add(row(1, session_id="gone-with-the-restart", customer=traces.customer_hash(MAYA)))
    assert sessions == {}
    client.post("/erase/start", json={"email": MAYA})
    client.post("/erase/check", json={"email": MAYA, "code": code_for(outbox)})
    assert fake_traces.rows == [] and fake_traces.erasures[0]["rows_deleted"] == 1


def shadow_chat(number, days_old):
    return {"number": number, "opened_at": NOW - timedelta(days=days_old), "opened_for": "x", "message": "m",
            "agent_reply": "r", "answered_at": NOW}


def test_shadow_chats_follow_the_same_rule_and_take_their_marks_with_them():
    from shadow import FakeShadowStore
    store = FakeShadowStore()
    for number, days in (("a", 89), ("b", 90), ("c", 91)):
        store.save(shadow_chat(number, days))
        store.mark(number, "Lena", "same")
    store.mark("c", "Marco", "worse")
    assert retention.purge_shadow(now=NOW, store=store) == 1
    assert sorted(store.rows) == ["a", "b"]
    assert sorted(m["number"] for m in store.marks()) == ["a", "b"]
    assert retention.purge_shadow(now=NOW, store=store) == 0
