"""Fast tests of the agent loop with a scripted fake model."""
import json
from datetime import UTC, datetime, timedelta

import pytest

import refunds
import tools
from agent import MAX_ROUNDS, answer
from conftest import reply, text, tool_use, unwrap
from handoff import HAND_OFF_REPLY

MAYA = "maya.ross@example.com"


def tool_result(model, call):
    """The tool result the loop sent back to the model on a given call."""
    return unwrap(model.calls[call]["messages"][-1]["content"][0]["content"])


def test_tool_use_then_final_text(fake_model):
    model = fake_model(
        reply(tool_use("find_order", {"number": "DS-20417"})),
        reply(text("Your order has shipped.")))
    result = answer("Where is DS-20417?", refunds.Context(MAYA))
    assert result.reply == "Your order has shipped."
    assert (result.action, result.rounds) == ("give_status", 2)
    assert len(model.calls) == 2
    assert tool_result(model, 1)["status"] == "shipped"


def stale(monkeypatch):
    """30h01m after the start of the news date 2026-10-21: the tools drop the date and set offer_person."""
    monkeypatch.setattr(tools, "clock", lambda: datetime(2026, 10, 21, tzinfo=UTC) + timedelta(hours=30, minutes=1))


def test_a_status_without_a_date_is_flagged_from_the_tool_result(fake_model, monkeypatch):
    stale(monkeypatch)
    model = fake_model(
        reply(tool_use("find_order", {"number": "DS-20417"})),
        reply(text("Your order has shipped.")))  # the words say nothing about a date or a person: the tool decides
    result = answer("Where is DS-20417?", refunds.Context(MAYA))
    assert tool_result(model, 1)["offer_person"] is True
    assert (result.action, result.no_date) == ("give_status", True)


def test_the_parcel_tool_without_a_date_flags_it_too(fake_model, monkeypatch):
    stale(monkeypatch)
    fake_model(
        reply(tool_use("delivery_status", {"tracking": "EP-7718204"})),
        reply(text("It is at the Leeds depot.")))
    assert answer("Where is the parcel?", refunds.Context(MAYA)).no_date is True


def test_a_dated_status_is_not_flagged_whatever_the_reply_says(fake_model):
    fake_model(
        reply(tool_use("find_order", {"number": "DS-20417"})),
        reply(text("It shipped. I can pass this chat to a person if you like.")))  # offering a person is only words
    result = answer("Where is DS-20417?", refunds.Context(MAYA))
    assert (result.action, result.no_date) == ("give_status", False)


def test_a_failed_lookup_is_not_a_status_and_not_flagged(fake_model):
    fake_model(
        reply(tool_use("find_order", {"number": "DS-20417"})),
        reply(text("Please enter your one-time code first.")))
    result = answer("Where is DS-20417?", refunds.Context(None))
    assert (result.action, result.no_date) == ("reply", False)


def test_usage_is_collected_per_call(fake_model):
    fake_model(reply(text("Hi.")))
    usage = []
    answer("Hello", refunds.Context(MAYA), usage)
    assert len(usage) == 1


def test_unverified_chat_gets_no_order_data(fake_model):
    model = fake_model(
        reply(tool_use("find_order", {"number": "DS-20417"})),
        reply(text("Please enter your one-time code first.")))
    answer("Where is DS-20417?", refunds.Context(None))
    assert "error" in tool_result(model, 1)
    assert list(tool_result(model, 1)) == ["error"]


@pytest.fixture
def cases(fake_systems):
    return lambda: [{"summary": c["short_description"], "history": json.loads(c["u_conversation"])}
                    for c in fake_systems.snow.cases]


def test_hand_off_writes_case_with_full_history(fake_model, cases):
    model = fake_model(reply(tool_use("hand_off", {"summary": "Wants a person.", "reason": "needs_human"})))
    history = [{"role": "user", "content": "Hi"},
               {"role": "assistant", "content": "Hello!"}]
    result = answer("Let me talk to a human", refunds.Context(MAYA), history=history)
    assert (result.action, result.reply) == ("hand_off", HAND_OFF_REPLY)
    assert len(model.calls) == 1
    [case] = cases()
    assert case["summary"] == "Wants a person."
    assert case["history"] == history + [
        {"role": "user", "content": "Let me talk to a human"}]


def test_tenth_round_opens_a_case(fake_model, cases):
    model = fake_model(*[reply(tool_use("find_order", {"number": "DS-20417"}))
                         for _ in range(MAX_ROUNDS + 1)])
    result = answer("Where is DS-20417?", refunds.Context(MAYA))
    assert (result.action, result.rounds) == ("hand_off", MAX_ROUNDS)
    assert result.reply == HAND_OFF_REPLY
    assert len(model.calls) == MAX_ROUNDS
    [case] = cases()
    assert case["history"] == [{"role": "user", "content": "Where is DS-20417?"}]


def test_plain_reply_has_no_case(fake_model, cases):
    fake_model(reply(text("Hi.")))
    assert answer("Hello", refunds.Context(MAYA)).action == "reply"


JACK = "jack.wilson@example.com"
C25 = "The monitor arrived with a crack in the screen. Order DS-20419."


def test_damage_on_arrival_goes_to_a_person_even_if_the_model_offers_a_refund(fake_model, fake_systems):
    """Damage on arrival is always a person's case (replay C25), whatever the model would do."""
    model = fake_model(
        reply(tool_use("prepare_return", {"number": "DS-20419", "line": 1})),
        reply(text("You can get a refund of 120.00 EUR. Shall I send it for approval?")))
    ctx = refunds.Context(JACK)
    result = answer(C25, ctx)
    assert result.action == "hand_off"
    assert HAND_OFF_REPLY in result.reply
    assert ctx.offer is None
    assert model.calls == []
    [case] = fake_systems.snow.cases
    assert "DS-20419" in case["short_description"]
    assert "damage" in case["short_description"].lower()


@pytest.mark.parametrize("message", [
    "Where is DS-20417?",
    "Can I return the mouse from DS-20417? It is still in the box.",
    "My order DS-20417 has not arrived.",
])
def test_no_damage_words_no_damage_hand_off(message, fake_model, fake_systems):
    fake_model(reply(text("ok")))
    result = answer(message, refunds.Context(MAYA))
    assert result.action == "reply"
    assert fake_systems.snow.cases == []
