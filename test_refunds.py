"""Fast tests of the two steps of a return in the chat (Phase 7): fakes for the model and every system."""
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app as app_module
import refunds
import servicenow
import tools
from conftest import reply, text, tool_use

TOM = "tom.baker@example.com"  # DS-20388: UK, one delivered line, delivered 2026-10-14, today is 2026-10-22
RETURN = json.dumps({"summary": "return", "intent": "return_request", "order_number": "DS-20388",
                     "needs_human": False, "language": "en"})
OTHER = json.dumps({"summary": "chat", "intent": "other", "order_number": None,
                    "needs_human": False, "language": "en"})

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def sessions(monkeypatch):
    monkeypatch.setattr(app_module, "SESSIONS", {"s": {"customer": TOM, "history": [], "offer": None}})


def send(message, sid="s"):
    return client.post("/chat", json={"session_id": sid, "message": message}).json()


def offer_return(fake_model, line=1, opened=None, number="DS-20388"):
    """The customer asks; the scripted model calls prepare_return and words the result."""
    args = {"number": number, "line": line}
    if opened is not None:
        args["opened"] = opened
    model = fake_model(reply(text(RETURN)), reply(tool_use("prepare_return", args)),
                       reply(text("You can return it: 120.00. Send the request?")))
    out = send("I want to return my laptop")
    return model, out


def tool_result(model):
    return json.loads(model.calls[2]["messages"][-1]["content"][0]["content"])


def test_eligible_return_makes_an_offer_and_writes_nothing(fake_model, fake_systems):
    model, _ = offer_return(fake_model)
    result = tool_result(model)
    assert (result["decision"], result["reason"], result["amount"]) == ("eligible", "within_window", "120.00")
    assert app_module.SESSIONS["s"]["offer"]["amount"] == Decimal("120.00")
    assert fake_systems.drafts.rows == {} and fake_systems.snow.tasks == []


def test_no_model_tool_creates_a_draft():
    assert {t["name"] for t in tools.TOOLS} == {"find_order", "delivery_status", "prepare_return", "hand_off"}


def test_yes_writes_one_draft_and_one_task_and_the_model_does_not_run(fake_model, fake_systems):
    model, _ = offer_return(fake_model)
    out = send("Yes please")
    assert len(model.calls) == 3  # nothing new
    assert out["reply"] == refunds.CONFIRMED_REPLY
    [draft] = fake_systems.drafts.rows.values()
    assert (draft[1], draft[2], draft[3], draft[5]) == ("DS-20388", 1, Decimal("120.00"), "W")
    assert len(fake_systems.snow.tasks) == 1
    assert app_module.SESSIONS["s"]["offer"] is None


def test_no_draft_without_a_yes(fake_model, fake_systems):
    offer_return(fake_model)
    fake_model(reply(text(OTHER)), reply(text("Anything else?")))
    send("Hmm, let me think")
    assert fake_systems.drafts.rows == {} and fake_systems.snow.tasks == []
    assert app_module.SESSIONS["s"]["offer"] is None  # any other message drops the offer


def test_yes_with_no_pending_offer_does_nothing(fake_model, fake_systems):
    fake_model(reply(text(OTHER)), reply(text("Yes to what?")))
    out = send("yes")
    assert out["reply"] != refunds.CONFIRMED_REPLY
    assert fake_systems.drafts.rows == {} and fake_systems.snow.tasks == []


def test_yes_after_not_eligible_does_nothing(fake_model, fake_systems, monkeypatch):
    monkeypatch.setattr(tools, "clock", lambda: datetime(2026, 12, 1, 12, 0, tzinfo=UTC))
    model, _ = offer_return(fake_model)
    assert tool_result(model)["decision"] == "not eligible"
    assert app_module.SESSIONS["s"]["offer"] is None
    fake_model(reply(text(OTHER)), reply(text("Sorry.")))
    send("yes")
    assert fake_systems.drafts.rows == {} and fake_systems.snow.tasks == []


@pytest.mark.parametrize("message", ["yes but only if it is quick", "Yes, and also change my address",
                                     "no", "yes?? maybe", "do not say yes"])
def test_a_yes_inside_a_longer_message_is_not_a_yes(fake_model, fake_systems, message):
    offer_return(fake_model)
    fake_model(reply(text(OTHER)), reply(text("Ok.")))
    send(message)
    assert fake_systems.drafts.rows == {} and fake_systems.snow.tasks == []
    assert app_module.SESSIONS["s"]["offer"] is None


@pytest.mark.parametrize("message", ["yes", "Yes.", " YES please! ", "confirm", "Yes, please"])
def test_the_short_yeses(message):
    assert refunds.is_yes(message)


def test_the_draft_amount_is_the_offered_one_even_if_the_systems_change(fake_model, fake_systems):
    offer_return(fake_model)
    fake_systems.ledger.orders["DS-20388"]["lines"][0]["unit_price"] = Decimal("1.00")
    send("yes")
    [draft] = fake_systems.drafts.rows.values()
    assert draft[3] == Decimal("120.00")


def test_two_yeses_in_a_row_make_one_draft_and_one_task(fake_model, fake_systems):
    offer_return(fake_model)
    send("yes")
    fake_model(reply(text(OTHER)), reply(text("It is already sent.")))
    send("yes")
    assert len(fake_systems.drafts.rows) == 1 and len(fake_systems.snow.tasks) == 1


def test_a_resent_yes_after_a_timeout_makes_the_same_draft_and_no_second_task(fake_model, fake_systems):
    offer_return(fake_model)
    fake_systems.snow.fail = servicenow.ServiceNowError("timeout")
    out = send("yes")
    assert out["reply"] == refunds.FAILED_REPLY and "refund" in out["reply"]
    assert len(fake_systems.drafts.rows) == 1 and fake_systems.snow.tasks == []
    assert app_module.SESSIONS["s"]["offer"] is not None  # the customer can try again
    fake_systems.snow.fail = None
    out = send("yes")
    assert out["reply"] == refunds.CONFIRMED_REPLY
    assert len(fake_systems.drafts.rows) == 1 and len(fake_systems.snow.tasks) == 1


def test_business_customer_goes_to_a_person(fake_model, fake_systems):
    fake_systems.ledger.orders["DS-20388"]["customer_type"] = "business"
    model, _ = offer_return(fake_model)
    assert (tool_result(model)["decision"], tool_result(model)["reason"]) == ("person", "business")
    assert app_module.SESSIONS["s"]["offer"] is None


def test_an_unknown_sku_goes_to_a_person(fake_model, fake_systems):
    fake_systems.ledger.orders["DS-20388"]["lines"][0]["kind"] = None
    model, _ = offer_return(fake_model)
    assert tool_result(model) == {"decision": "person", "reason": "unknown_product"}


def test_unverified_customer_gets_nothing(fake_model, fake_systems):
    app_module.SESSIONS["u"] = {"customer": None, "history": [], "offer": None}
    fake_model(reply(text(RETURN)), reply(tool_use("prepare_return", {"number": "DS-20388", "line": 1})),
               reply(text("Please enter your code first.")))
    send("return my laptop", "u")
    assert app_module.SESSIONS["u"]["offer"] is None
    assert fake_systems.drafts.rows == {}


def test_someone_elses_order_gives_nothing(fake_model, fake_systems):
    model, _ = offer_return(fake_model, number="DS-20417")  # Maya's order
    assert tool_result(model) == {"error": "no such order for this customer"}
    assert app_module.SESSIONS["s"]["offer"] is None


def test_a_wrong_line_lists_the_lines(fake_model):
    model, _ = offer_return(fake_model, line=9)
    assert tool_result(model) == {"error": "no such line in this order",
                                  "lines": [{"line": 1, "item": "Aero 14 laptop"}]}


def test_the_fixed_replies_never_say_refunded_or_done():
    for sentence in (refunds.CONFIRMED_REPLY, refunds.FAILED_REPLY):
        assert "refunded" not in sentence.lower() and "done" not in sentence.lower()


def test_the_model_cannot_write_a_draft_by_asking_for_a_tool(fake_model, fake_systems):
    fake_model(reply(text(RETURN)), reply(tool_use("create_draft", {"number": "DS-20388", "line": 1})))
    with pytest.raises(KeyError):  # not a tool: there is nothing to run, and nothing was written
        send("return my laptop")
    assert fake_systems.drafts.rows == {}
