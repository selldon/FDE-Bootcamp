"""Fast tests of the hand-off (Phase 8): triggers, the summary check, one case per session, ServiceNow down."""
import json

import pytest
from fastapi.testclient import TestClient

import app as app_module
import handoff
import refunds
import servicenow
import tools
from conftest import reply, text, tool_use

TOM = "tom.baker@example.com"
OTHER = json.dumps({"summary": "chat", "intent": "other", "order_number": None,
                    "needs_human": False, "language": "en"})
PERSON = json.dumps({"summary": "wants a person", "intent": "other", "order_number": None,
                     "needs_human": True, "language": "en"})
POLICY = json.dumps({"summary": "policy", "intent": "policy_question", "order_number": None,
                     "needs_human": False, "language": "en"})
STATUS = json.dumps({"summary": "status", "intent": "order_status", "order_number": "DS-20388",
                     "needs_human": False, "language": "en"})
RETURN = json.dumps({"summary": "return", "intent": "return_request", "order_number": "DS-20388",
                     "needs_human": False, "language": "en"})

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def sessions(monkeypatch):
    monkeypatch.setattr(app_module, "SESSIONS", {"s": {"customer": TOM, "history": [], "offer": None}})


def send(message, sid="s"):
    return client.post("/chat", json={"session_id": sid, "message": message}).json()


def history(*messages):
    return [{"role": "user", "content": m} for m in messages]


# the three triggers

def test_request_for_a_person_opens_one_case(fake_model, fake_systems):
    fake_model(reply(text(PERSON)))
    out = send("Let me talk to a human about DS-20388")
    assert handoff.HAND_OFF_REPLY in out["reply"]
    [case] = fake_systems.snow.cases
    assert "DS-20388" in case["short_description"]


def test_not_covered_topic_opens_one_case(fake_model, fake_systems):
    fake_model(reply(text(POLICY)))
    send("What is your return policy?")
    assert len(fake_systems.snow.cases) == 1


def test_the_model_hand_off_tool_opens_one_case(fake_model, fake_systems):
    fake_model(reply(text(OTHER)),
               reply(tool_use("hand_off", {"summary": "Order DS-20388: the customer asked for a person.",
                                           "reason": "needs_human"})))
    out = send("About DS-20388, can I have a person?")
    assert handoff.HAND_OFF_REPLY in out["reply"]
    [case] = fake_systems.snow.cases
    assert case["short_description"] == "Order DS-20388: the customer asked for a person."


def failing_order(fake_model, n):
    """The classifier says order_status, the scripted model asks for an order that is not the customer's."""
    responses = []
    for _ in range(n):
        responses += [reply(text(STATUS)), reply(tool_use("find_order", {"number": "DS-99999"})),
                      reply(text("I could not find that order."))]
    return fake_model(*responses)


def test_second_failed_try_opens_the_case_the_first_does_not(fake_model, fake_systems):
    model = failing_order(fake_model, 2)
    first = send("Where is DS-99999?")
    assert fake_systems.snow.cases == [] and handoff.HAND_OFF_REPLY not in first["reply"]
    second = send("Where is DS-99999?")
    assert handoff.HAND_OFF_REPLY in second["reply"]
    assert len(fake_systems.snow.cases) == 1
    assert len(model.calls) == 5  # the model did not get to word the second failure


def test_declined_replies_to_an_offer_count_as_failed_tries(fake_model, fake_systems):
    fake_model(reply(text(RETURN)), reply(tool_use("prepare_return", {"line": 1, "number": "DS-20388"})),
               reply(text("You can return it: 120.00. Send the request?")),
               reply(text(OTHER)), reply(text("Take your time.")),
               reply(text(OTHER)))
    send("I want to return my laptop")
    send("Hmm, not sure")
    assert fake_systems.snow.cases == []
    assert app_module.SESSIONS["s"]["failed"] == 1


# the summary check

LOG = history("Order DS-20388 arrived broken, I paid 120.00 EUR. I want a person.")


def test_summary_with_the_right_number_and_reason_is_kept(fake_systems):
    ctx = refunds.Context(TOM)
    handoff.open_case(ctx, "Order DS-20388 arrived broken; the customer wants a person.", LOG, "needs_human", "t")
    assert fake_systems.snow.cases[0]["short_description"] == "Order DS-20388 arrived broken; the customer wants a person."


@pytest.mark.parametrize("summary", [
    "Order DS-20999: the customer wants a person.",  # invented order number
    "Order DS-20388: the customer wants a person, refund of 150.00 EUR.",  # invented amount
    "Order DS-20388: the customer wants a person since 2026-01-01.",  # invented date
    "Order DS-20388: the customer wants a person; mail x@example.com.",  # invented email
    "The customer wants a person.",  # no order number
    "Order DS-20388: it arrived broken.",  # no reason
    "",
    None,
])
def test_a_summary_that_fails_the_check_is_replaced_by_the_template(summary, fake_systems):
    ctx = refunds.Context(TOM)
    handoff.open_case(ctx, summary, LOG, "needs_human", "asked for a person")
    sent = fake_systems.snow.cases[0]["short_description"]
    assert sent == ("Order: DS-20388. Reason: the customer asked for a person or is angry. "
                    "Trigger: asked for a person.")


def test_the_case_carries_the_chat(fake_systems):
    log = [{"role": "user", "content": "Hi DS-20388"}, {"role": "assistant", "content": "Hello!"}]
    handoff.open_case(refunds.Context(TOM), None, log, "needs_human", "t")
    assert json.loads(fake_systems.snow.cases[0]["u_conversation"]) == log


# one case per session, and ServiceNow down

def test_a_second_trigger_in_the_session_opens_no_second_case(fake_model, fake_systems):
    fake_model(reply(text(PERSON)), reply(text(PERSON)))
    send("A person please")
    out = send("A person please, now")
    assert handoff.HAND_OFF_REPLY in out["reply"]
    assert len(fake_systems.snow.cases) == 1
    assert app_module.SESSIONS["s"]["handed_off"] is True


def test_servicenow_down_tells_the_customer_nothing_was_passed_on(fake_model, fake_systems):
    fake_systems.snow.fail = servicenow.ServiceNowError("down")
    fake_model(reply(text(PERSON)), reply(text(PERSON)))
    out = send("A person please")
    assert handoff.DOWN_REPLY in out["reply"]
    assert "passed this" not in out["reply"] and fake_systems.snow.cases == []
    assert app_module.SESSIONS["s"]["handed_off"] is False
    fake_systems.snow.fail = None  # the next trigger tries again
    assert handoff.HAND_OFF_REPLY in send("A person please")["reply"]
    assert len(fake_systems.snow.cases) == 1


def test_the_old_case_file_writer_is_gone():
    assert not hasattr(tools, "open_case") and not hasattr(tools, "CASES")
