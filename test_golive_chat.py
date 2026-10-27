"""Fast tests of the go-live routing in /chat: the fake model, fake systems and a FakeGoLiveStore."""
import copy
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import golive
import handoff
import servicenow
from conftest import reply, text, tool_use
from golive import ASSISTANT, CONTROL, PERSON

client = TestClient(app_module.app)

ORDER = json.dumps({"summary": "order", "intent": "order_status", "order_number": None, "needs_human": False,
                    "damaged": False, "language": "en"})
POLICY = json.dumps({"summary": "policy", "intent": "policy_question", "order_number": None, "needs_human": False,
                     "damaged": False, "language": "en"})
RETURN = json.dumps({"summary": "return", "intent": "return_request", "order_number": "DS-20388",
                     "needs_human": False, "damaged": False, "language": "en"})
OTHER = json.dumps({"summary": "chat", "intent": "other", "order_number": None, "needs_human": False,
                    "damaged": False, "language": "en"})
TOM = "tom.baker@example.com"


@pytest.fixture(autouse=True)
def sessions(monkeypatch):
    monkeypatch.setattr(app_module, "SESSIONS", {})


def visitor_in(group, share):
    """A visitor id that the real hash puts in this group at this share."""
    return next(v for v in (f"v{i}" for i in range(10_000)) if golive.group_of(v, share) == group)


def send(message="Where is my order?", sid=None, visitor=None, **extra):
    body = {"session_id": sid, "message": message, "visitor_id": visitor} | extra
    return client.post("/chat", json=body).json()


def settings(fake_golive, **changes):
    fake_golive.set_settings(**changes)


def test_switch_off_sends_a_new_chat_to_a_person_within_the_request_and_no_model_runs(
        fake_golive, fake_model, fake_systems):
    settings(fake_golive, on=False)
    model = fake_model()  # no canned replies: a model call would fail
    out = send(visitor="anyone")
    assert out["reply"] == handoff.HAND_OFF_REPLY and model.calls == []
    assert len(fake_systems.snow.cases) == 1
    [row] = fake_golive.chats()
    assert (row["group_name"], row["handed_off"], row["outcome"]) == (PERSON, True, "handed_off")


def test_control_goes_to_the_live_queue_with_fixed_text_and_the_chat(fake_golive, fake_model, fake_systems):
    settings(fake_golive, share=0.25)
    model = fake_model()
    out = send("Where is DS-20417? my email is a@b.com", visitor=visitor_in(CONTROL, 0.25))
    assert out["reply"] == handoff.HAND_OFF_REPLY and model.calls == []
    [case] = fake_systems.snow.cases
    assert case["short_description"] == servicenow.QUEUE_SUMMARY
    assert "DS-20417" in case["u_conversation"] and "DS-20417" not in case["short_description"]
    [row] = fake_golive.chats()
    assert (row["group_name"], row["outcome"], row["handed_off"], row["cost"]) == (CONTROL, "queued", True, None)


def test_the_live_queue_is_the_interaction_table():
    assert servicenow.CASES == "/api/now/table/interaction"
    seen = []
    servicenow.queue_chat([{"role": "user", "content": "hi"}], lambda method, path, body=None: (
        seen.append((method, path)) or {"result": {"sys_id": "x"}}))
    assert seen == [("POST", servicenow.CASES)]


def test_control_chat_makes_one_queue_entry_however_many_messages(fake_golive, fake_systems):
    settings(fake_golive, share=0.25)
    v = visitor_in(CONTROL, 0.25)
    first = send(visitor=v)
    send("Any news?", first["session_id"], visitor=v)
    assert len(fake_systems.snow.cases) == 1 and len(fake_golive.chats()) == 1


def test_assistant_group_runs_today_s_chat_and_logs_tokens_cost_and_labels(fake_golive, fake_model, fake_systems):
    settings(fake_golive, share=0.25)
    model = fake_model(reply(text(ORDER)), reply(text("It ships Monday.")))
    out = send(visitor=visitor_in(ASSISTANT, 0.25), simulated=True, sim_day=3)
    assert "It ships Monday." in out["reply"] and len(model.calls) == 2
    [row] = fake_golive.chats()
    assert (row["group_name"], row["intent"], row["outcome"], row["handed_off"]) == (ASSISTANT, "order_status",
                                                                                      "reply", False)
    assert (row["input_tokens"], row["output_tokens"]) == (2, 2) and row["cost"] > 0  # classify + answer
    assert (row["simulated"], row["sim_day"]) == (True, 3)
    assert fake_systems.snow.cases == []


def test_a_real_visitor_is_not_marked_simulated(fake_golive, fake_model):
    fake_model(reply(text(ORDER)), reply(text("ok")))
    send(visitor="v1")
    assert fake_golive.chats()[0]["simulated"] is False and fake_golive.chats()[0]["sim_day"] is None


def test_one_row_per_chat_brought_up_to_date_each_turn(fake_golive, fake_model):
    fake_model(reply(text(ORDER)), reply(text("one")), reply(text(OTHER)), reply(text("two")))
    first = send(visitor="v1")
    send("And the date?", first["session_id"], visitor="v1")
    [row] = fake_golive.chats()
    assert row["intent"] == "order_status" and (row["input_tokens"], row["output_tokens"]) == (4, 4)


def test_an_intent_that_is_not_live_goes_to_a_person(fake_golive, fake_model, fake_systems):
    settings(fake_golive, intents=["order_status"])
    fake_model(reply(text(POLICY)))
    out = send("What is your return policy?", visitor="v1")
    assert handoff.HAND_OFF_REPLY in out["reply"] and len(fake_systems.snow.cases) == 1
    [row] = fake_golive.chats()
    assert (row["group_name"], row["intent"], row["handed_off"]) == (PERSON, "policy_question", True)
    assert row["cost"] is not None  # the classifier call happened and is counted


def test_chat_open_when_the_switch_goes_off_is_handed_to_a_person_with_its_transcript(
        fake_golive, fake_model, fake_systems):
    fake_model(reply(text(ORDER)), reply(text("It ships Monday.")))
    first = send("Where is DS-20417?", visitor="v1")
    assert fake_systems.snow.cases == [] and fake_golive.chats()[0]["group_name"] == ASSISTANT
    settings(fake_golive, on=False)
    model = fake_model()  # the next message must not reach the model
    out = send("Which day exactly?", first["session_id"], visitor="v1")
    assert out["reply"] == handoff.HAND_OFF_REPLY and model.calls == []
    [case] = fake_systems.snow.cases
    said = [m["content"] for m in json.loads(case["u_conversation"])]
    assert any("DS-20417" in c for c in said) and any("It ships Monday." in c for c in said)
    assert "Which day exactly?" in said
    [row] = fake_golive.chats()  # still one row, now a person's
    assert (row["group_name"], row["handed_off"]) == (PERSON, True)
    # and a further message opens no second case
    send("Hello?", first["session_id"], visitor="v1")
    assert len(fake_systems.snow.cases) == 1


def test_switch_off_with_servicenow_down_tells_the_visitor_and_tries_again(fake_golive, fake_model, fake_systems):
    fake_model(reply(text(ORDER)), reply(text("ok")))
    first = send(visitor="v1")
    settings(fake_golive, on=False)
    fake_systems.snow.fail = servicenow.ServiceNowError("down")
    out = send("hello", first["session_id"], visitor="v1")
    assert out["reply"] == handoff.DOWN_REPLY and fake_golive.chats()[0]["handed_off"] is False
    fake_systems.snow.fail = None
    assert send("hello again", first["session_id"], visitor="v1")["reply"] == handoff.HAND_OFF_REPLY
    assert len(fake_systems.snow.cases) == 1 and fake_golive.chats()[0]["handed_off"] is True


def test_the_group_does_not_change_when_the_share_widens(fake_golive, fake_model, fake_systems):
    settings(fake_golive, share=0.05)
    v = visitor_in(ASSISTANT, 0.05)
    fake_model(reply(text(ORDER)), reply(text("ok")))
    send(visitor=v)
    settings(fake_golive, share=0.25)
    fake_model(reply(text(OTHER)), reply(text("ok")))
    first = next(iter(app_module.SESSIONS))
    send("more", first, visitor=v)
    assert fake_golive.chats()[0]["group_name"] == ASSISTANT and fake_systems.snow.cases == []


def test_settings_that_cannot_be_read_mean_a_person(fake_golive, fake_model, fake_systems, monkeypatch):
    def boom():
        raise RuntimeError("database down")
    monkeypatch.setattr(fake_golive, "settings", boom)
    model = fake_model()
    out = send(visitor="v1")
    assert out["reply"] == handoff.HAND_OFF_REPLY and model.calls == [] and len(fake_systems.snow.cases) == 1


def test_a_failed_log_write_never_blocks_the_chat(fake_golive, fake_model, monkeypatch):
    def boom(row):
        raise RuntimeError("database down")
    monkeypatch.setattr(fake_golive, "save_chat", boom)
    fake_model(reply(text(ORDER)), reply(text("It ships Monday.")))
    out = send(visitor="v1")
    assert "It ships Monday." in out["reply"] and app_module.record_failures == 1


def test_a_visitor_without_an_id_is_grouped_by_the_session(fake_golive, fake_model):
    fake_model(reply(text(ORDER)), reply(text("ok")))
    out = send()
    assert fake_golive.chats()[0]["visitor_id"] == out["session_id"]


# ---- no refund is paid by the assistant, at any share ----------------------------------------------------------

def test_at_25_percent_a_return_still_ends_in_a_draft_and_a_task_only(fake_golive, fake_model, fake_systems):
    settings(fake_golive, share=0.25, intents=["order_status", "return_request"])
    app_module.SESSIONS["s"] = {"customer": TOM, "history": [], "offer": None}
    ledger_before = copy.deepcopy(fake_systems.ledger.orders)
    v = visitor_in(ASSISTANT, 0.25)
    fake_model(reply(text(RETURN)), reply(tool_use("prepare_return", {"number": "DS-20388", "line": 1})),
               reply(text("You can return it: 120.00. Send the request?")))
    send("I want to return my laptop", "s", visitor=v)
    assert fake_systems.drafts.rows == {}  # an offer writes nothing
    fake_model()  # the yes runs no model
    send("Yes please", "s", visitor=v)
    [draft] = fake_systems.drafts.rows.values()
    assert draft[5] == "W" and len(fake_systems.snow.tasks) == 1 and fake_systems.snow.cases == []
    assert fake_systems.ledger.orders == ledger_before
    [row] = fake_golive.chats()
    assert (row["intent"], row["outcome"]) == ("return_request", "draft")


SOURCES = sorted(p for p in Path(__file__).parent.glob("*.py") if not p.name.startswith(("test_", "conftest")))


def test_the_writer_account_and_the_staging_table_are_used_by_drafts_only():
    for path in SOURCES:
        code = path.read_text()
        if path.name in ("drafts.py", "config.py", "probe_live.py"):
            continue
        assert "ledgerline_writer" not in code and "LL_RTN_REQ_STG" not in code.replace("LL_RTN_REQ_STG\"", ""), path


def test_the_read_side_of_ledgerline_has_no_write_statement():
    code = Path("ledgerline.py").read_text()
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|ALTER)\b", code)


def test_the_group_and_log_module_touches_no_other_system():
    imports = set(re.findall(r"^(?:import|from) (\w+)", Path("golive.py").read_text(), re.MULTILINE))
    assert not imports & {"drafts", "ledgerline", "refunds", "servicenow", "handoff", "llm", "oracledb"}


# ---- a model call that fails: the chat goes to a person, never an error to the customer --------------------------

def credit_error():
    """The 400 the API gave when the account ran out of credit."""
    import anthropic
    import httpx
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request, json={"type": "error", "error": {
        "type": "invalid_request_error", "message": "Your credit balance is too low to access the Anthropic API."}})
    return anthropic.BadRequestError("credit balance is too low", response=response, body=None)


def model_that_fails_after(monkeypatch, good_replies, error):
    """The first `len(good_replies)` calls answer; every later call raises `error`."""
    import llm
    replies = list(good_replies)

    def create(**kwargs):
        if replies:
            return replies.pop(0)
        raise error

    monkeypatch.setattr(llm.client, "messages", type("M", (), {"create": staticmethod(create)})())


def test_a_failed_classify_call_hands_the_chat_to_a_person_not_an_error(fake_golive, fake_systems, monkeypatch):
    settings(fake_golive, share=0.25)
    model_that_fails_after(monkeypatch, [], credit_error())
    response = client.post("/chat", json={"message": "Where is DS-20388?", "visitor_id": visitor_in(ASSISTANT, 0.25)})
    assert response.status_code == 200
    assert response.json()["reply"] == handoff.HAND_OFF_REPLY
    assert len(fake_systems.snow.cases) == 1
    [row] = fake_golive.chats()
    # still the assistant group (it was assigned there), so the lines count the failure instead of hiding it
    assert (row["group_name"], row["outcome"], row["handed_off"]) == (ASSISTANT, "handed_off", True)


def test_a_failure_in_the_answer_call_hands_the_chat_to_a_person_too(fake_golive, fake_systems, monkeypatch):
    settings(fake_golive, share=0.25)
    model_that_fails_after(monkeypatch, [reply(text(ORDER))], RuntimeError("connection reset"))
    out = send("Where is DS-20388?", visitor=visitor_in(ASSISTANT, 0.25))
    assert out["reply"] == handoff.HAND_OFF_REPLY and len(fake_systems.snow.cases) == 1


def test_a_failure_later_in_an_open_chat_hands_it_over_once_with_the_chat_so_far(fake_golive, fake_systems,
                                                                                monkeypatch):
    settings(fake_golive, share=0.25)
    v = visitor_in(ASSISTANT, 0.25)
    model_that_fails_after(monkeypatch, [reply(text(ORDER)), reply(text("It ships Monday."))], credit_error())
    first = send("Where is DS-20388?", visitor=v)
    second = send("And the invoice?", first["session_id"], visitor=v)
    third = send("Hello?", first["session_id"], visitor=v)
    assert second["reply"] == handoff.HAND_OFF_REPLY and third["reply"] == handoff.HAND_OFF_REPLY
    [case] = fake_systems.snow.cases  # one case for the chat, not one per message
    assert "It ships Monday." in case["u_conversation"] and "And the invoice?" in case["u_conversation"]
    assert fake_golive.chats()[0]["handed_off"] is True
