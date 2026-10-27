"""Fast tests of the shadow store: no network, no database."""
import re
import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest
from psycopg import sql

import config
import drafts
import handoff
import refunds
import servicenow
import shadow
import traces
from agent import Result
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
                             "would_have", "state", "agent_reply", "answered_at", "input_tokens", "output_tokens")
    create, *alters = shadow.tables("shadow_chats")
    text = create.as_string(None) if isinstance(create, sql.Composable) else str(create)
    columns = set(re.findall(r"^\s*(?:\(|)\s*(\w+) (?:text|timestamptz|jsonb)", text.replace(", ", ",\n"), re.MULTILINE))
    added = {re.search(r"ADD COLUMN IF NOT EXISTS \"?(\w+)\"? int", a.as_string(None)).group(1) for a in alters}
    assert columns | added == set(shadow.FIELDS) and added == {"input_tokens", "output_tokens"}
    row = FakeShadowStore()
    row.save(chat("INT001", session_id="s1", customer_hash="abc"))
    assert set(row.rows["INT001"]) == set(shadow.FIELDS)


# ---- the worker -------------------------------------------------------------------------------------------------


def snow_chat(n, minutes, state="work_in_progress", reply=None, email="maya.ross@example.com"):
    opened = T0 + timedelta(minutes=minutes)
    text = f"Maya Ross: Where is DS-{n}?" + (f"\nAgent: {reply}" if reply else "")
    return {"number": f"IMS{n:07}", "opened_at": opened.strftime("%Y-%m-%d %H:%M:%S"), "state": state,
            "u_market": "US", "opened_for": email, "transcript": text}


class FakeReader:
    """A ServiceNow that answers the two queries the worker asks, like the stand-in does."""

    def __init__(self, chats):
        self.chats, self.paths, self.failures = chats, [], []

    def __call__(self, path):
        self.paths.append(path)
        if self.failures:
            raise self.failures.pop(0)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        rows = list(self.chats)
        for part in params["sysparm_query"][0].split("^"):
            if part.startswith("ORDERBY"):
                rows.sort(key=lambda c: c[part[7:]])
            elif ">" in part:
                field, value = part.split(">", 1)
                rows = [c for c in rows if c[field] > value]
            elif "=" in part:
                field, value = part.split("=", 1)
                rows = [c for c in rows if c[field] == value]
        start, size = int(params["sysparm_offset"][0]), int(params["sysparm_limit"][0])
        return {"result": rows[start:start + size]}


class Answerer:
    def __init__(self, fail_on=()):
        self.seen, self.fail_on = [], set(fail_on)

    def __call__(self, message, ctx):
        self.seen.append((message, ctx.customer, ctx.session_id, ctx.market))
        if message in self.fail_on:
            raise RuntimeError("Claude is down")
        refunds.get_servicenow().create_case("summary", [], ctx.customer)  # lands in the fake, not ServiceNow
        return Result("It ships Monday.", "reply", 1)


@pytest.fixture(autouse=True)
def nothing_real(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a real writer was called")
    monkeypatch.setattr(servicenow, "send", boom)
    monkeypatch.setattr(drafts, "create", boom)
    monkeypatch.setattr(config, "ledgerline_writer", boom)
    monkeypatch.setattr(config, "servicenow", boom)
    yield
    refunds.set_systems()
    traces.set_sink(None)


COVERED_INTENT = {"summary": "Where is the order", "intent": "order_status", "order_number": "DS-1",
                  "needs_human": False, "damaged": False, "language": "en"}


@pytest.fixture(autouse=True)
def fake_classifier(monkeypatch):
    """No test here calls Claude: the worker's classifier is replaced, and it records a trace like `llm.ask` does."""
    def classify(message):
        traces.record("ask", "m", message, "{}", type("U", (), {"input_tokens": 100, "output_tokens": 10})(), None)
        return dict(COVERED_INTENT)
    monkeypatch.setattr(shadow, "real_classifier", classify)


def noop_sleep(_):
    pass


def test_a_tick_stores_new_chats_only_and_nothing_real_is_written():
    store, reader, answerer = FakeShadowStore(), FakeReader([snow_chat(1, -60), snow_chat(2, 5), snow_chat(3, 9)]), Answerer()
    done = shadow.poll(reader, store, answerer, since=T0, sleep=noop_sleep)  # the old chat is before `since`
    assert done == {"stored": 2, "closed": 0, "errors": 0, "clashes": 0}
    assert sorted(store.rows) == ["IMS0000002", "IMS0000003"]
    row = store.rows["IMS0000002"]
    assert row["message"] == "Where is DS-2?" and row["answer"] == "It ships Monday." and row["action"] == "reply"
    assert row["would_have"]["cases"][0]["short_description"] == "summary"  # what the fake recorded
    assert row["opened_at"] == T0 + timedelta(minutes=5) and row["market"] == "US"


def test_a_verified_opened_for_reaches_the_order_tools():
    answerer = Answerer()
    shadow.poll(FakeReader([snow_chat(7, 1, email="tom.baker@example.com")]), FakeShadowStore(), answerer, since=T0, sleep=noop_sleep)
    assert answerer.seen == [("Where is DS-7?", "tom.baker@example.com", "shadow-IMS0000007", "US")]


def test_a_chat_answered_twice_is_stored_once():
    store, reader, answerer = FakeShadowStore(), FakeReader([snow_chat(1, 5)]), Answerer()
    shadow.poll(reader, store, answerer, since=T0, sleep=noop_sleep)
    done = shadow.poll(reader, store, answerer, since=T0, sleep=noop_sleep)
    assert done["stored"] == 0 and len(store.rows) == 1 and len(answerer.seen) == 1


def test_a_new_chat_with_a_number_already_stored_is_reported_not_swallowed(caplog):
    store, answerer = FakeShadowStore(), Answerer()
    shadow.poll(FakeReader([snow_chat(1, 5)]), store, answerer, since=T0, sleep=noop_sleep)
    assert len(answerer.seen) == 1
    again = FakeReader([snow_chat(1, 8), snow_chat(2, 9)])  # the same number, opened later: a source that restarted its count
    with caplog.at_level("WARNING", logger="shadow"):
        done = shadow.poll(again, store, answerer, since=T0, sleep=noop_sleep)
    assert done["clashes"] == 1 and done["stored"] == 1 and done["errors"] == 0
    assert "IMS0000001" in caplog.text and "already stored" in caplog.text
    assert len(answerer.seen) == 2  # the clashing chat is not answered again: that would spend a model call for nothing
    assert store.rows["IMS0000001"]["opened_at"] == T0 + timedelta(minutes=5)  # the stored one is untouched


def test_a_clash_fails_a_single_run(monkeypatch):
    monkeypatch.setattr(shadow, "tick", lambda store: {"stored": 0, "closed": 0, "errors": 0, "clashes": 1})
    monkeypatch.setattr(shadow, "ShadowStore", lambda: type("S", (), {"create_tables": lambda self: None})())
    assert shadow.main(["--once"]) == 1


def test_an_empty_table_without_a_start_stores_nothing():
    store = FakeShadowStore()
    assert shadow.poll(FakeReader([snow_chat(1, -5)]), store, Answerer(), sleep=noop_sleep)["stored"] == 0


def test_a_closed_chat_gets_the_agents_reply_once():
    store, chats = FakeShadowStore(), [snow_chat(1, 5)]
    shadow.poll(FakeReader(chats), store, Answerer(), since=T0, sleep=noop_sleep)
    chats[0] = snow_chat(1, 5, state="closed_complete", reply="Sent today.")
    assert shadow.poll(FakeReader(chats), store, Answerer(), since=T0, sleep=noop_sleep)["closed"] == 1
    assert store.rows["IMS0000001"]["agent_reply"] == "Sent today."
    chats[0] = snow_chat(1, 5, state="closed_complete", reply="Another reply.")
    assert shadow.poll(FakeReader(chats), store, Answerer(), since=T0, sleep=noop_sleep)["closed"] == 0
    assert store.rows["IMS0000001"]["agent_reply"] == "Sent today."


def test_429_is_waited_out_and_retried():
    reader, waits = FakeReader([snow_chat(1, 5)]), []
    reader.failures = [shadow.ReadError("429", 429, 2.0)]
    done = shadow.poll(reader, FakeShadowStore(), Answerer(), since=T0, sleep=waits.append)
    assert done["stored"] == 1 and done["errors"] == 0 and waits == [2.0]


def test_a_server_error_is_counted_and_retried_at_the_next_tick():
    store, reader = FakeShadowStore(), FakeReader([snow_chat(1, 5)])
    reader.failures = [shadow.ReadError("503", 503)]
    assert shadow.poll(reader, store, Answerer(), since=T0, sleep=noop_sleep) == {"stored": 0, "closed": 0, "errors": 1, "clashes": 0}
    assert shadow.poll(reader, store, Answerer(), since=T0, sleep=noop_sleep)["stored"] == 1


def test_a_bad_chat_stops_the_list_and_is_retried_so_no_chat_is_skipped():
    store, reader = FakeShadowStore(), FakeReader([snow_chat(1, 5), snow_chat(2, 6), snow_chat(3, 7)])
    done = shadow.poll(reader, store, Answerer(fail_on={"Where is DS-2?"}), since=T0, sleep=noop_sleep)
    assert done["stored"] == 1 and done["errors"] == 1 and list(store.rows) == ["IMS0000001"]
    done = shadow.poll(reader, store, Answerer(), since=T0, sleep=noop_sleep)
    assert done["stored"] == 2 and sorted(store.rows) == ["IMS0000001", "IMS0000002", "IMS0000003"]


def test_new_chats_are_read_page_by_page():
    chats = [snow_chat(i, i) for i in range(1, 121)]
    rows = shadow.query(FakeReader(chats), "ORDERBYopened_at", noop_sleep)
    assert len(rows) == 120


def test_the_report_prints_the_last_20_rows():
    store = FakeShadowStore()
    for i in range(25):
        store.save(chat(f"INT{i:03}", minutes=i))
    lines = []
    shadow.report(store, out=lines.append)
    assert lines[0] == "20 chats (newest first)" and sum(1 for line in lines if line.startswith("INT")) == 20
    assert lines[1].startswith("INT024") and any("It ships Monday." in line for line in lines)


def test_the_message_and_the_reply_are_cut_from_the_transcript():
    assert shadow.customer_message("Maya Ross: Where is it?\nAgent: Soon.") == "Where is it?"
    assert shadow.agent_reply("Maya Ross: Where is it?\nAgent: Soon.") == "Soon."
    assert shadow.agent_reply("Maya Ross: Where is it?") is None


# ---- the gate and what is stored ----------------------------------------------------------------------------------


def answer_one(message, classifier=None, answerer=None):
    chat_row = snow_chat(1, 5)
    chat_row["transcript"] = f"Maya Ross: {message}"
    answerer = answerer or Answerer()
    return shadow.shadow_answer(chat_row, answerer, classifier), answerer


def test_a_covered_chat_stores_its_intent_and_the_tokens_of_every_call():
    class Both(Answerer):
        def __call__(self, message, ctx):
            traces.record("chat", "m", message, "r", type("U", (), {"input_tokens": 50, "output_tokens": 5})(), None)
            return super().__call__(message, ctx)

    row, answerer = answer_one("Where is DS-1?", answerer=Both())
    assert row["intent"] == "order_status" and row["action"] == "reply" and row["answer"] == "It ships Monday."
    assert (row["input_tokens"], row["output_tokens"]) == (150, 15)  # the classify call and the answer call
    assert len(answerer.seen) == 1


@pytest.mark.parametrize("flags, reason", [({"needs_human": True}, "needs_human"), ({"damaged": True}, "damaged"),
                                           ({"intent": "product_question"}, "not_covered")])
def test_a_gated_chat_is_a_hand_off_and_answer_is_not_called(flags, reason):
    intent = {**COVERED_INTENT, **flags}
    row, answerer = answer_one("I want a person", classifier=lambda m: intent)
    assert answerer.seen == [] and row["action"] == "hand_off" and row["intent"] == intent["intent"]
    assert row["answer"] == handoff.HAND_OFF_REPLY  # the live text, from open_case against the fake ServiceNow
    assert len(row["would_have"]["cases"]) == 1


def test_a_card_number_is_stored_masked_and_never_reaches_the_model():
    seen = []

    def classifier(message):
        seen.append(message)
        return dict(COVERED_INTENT)

    class Echo(Answerer):
        def __call__(self, message, ctx):
            super().__call__(message, ctx)
            return Result(f"You wrote {message}", "reply", 1)

    row, answerer = answer_one("Charge 4111 1111 1111 1111 please", classifier, Echo())
    assert "4111" not in row["message"] and "4111" not in row["answer"]
    assert "4111" not in seen[0] and "4111" not in answerer.seen[0][0]


def test_a_chat_without_any_model_call_has_no_tokens_not_zero():
    row, _ = answer_one("hi", classifier=lambda m: dict(COVERED_INTENT))  # a fake that records no trace
    assert row["input_tokens"] is None and row["output_tokens"] is None
