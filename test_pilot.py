"""Fast tests of the pilot numbers: no network, no database, no model."""
from datetime import UTC, datetime, timedelta

import pytest

import pilot
from shadow import FakeShadowStore

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def chat(number, days=0, **extra):
    row = {"number": number, "opened_at": T0 + timedelta(days=days), "opened_for": "x@example.com", "market": "US",
           "message": "Where is DS-1?", "intent": "order_status", "action": "give_status", "answer": "Monday.",
           "answered_at": T0, "input_tokens": 1000, "output_tokens": 100}
    return row | extra


def store_with(*rows):
    store = FakeShadowStore()
    for row in rows:
        store.save(row)
    return store


def mixed():
    return store_with(
        chat("INT1"),
        chat("INT2", days=1, market="DE", action="hand_off"),
        chat("INT3", days=1, market=None, intent="return_request", action="start_return"),
        chat("INT4", days=2, intent=None, action="reply", input_tokens=None, output_tokens=None),
        chat("INT5", days=2, intent="product_question", action="hand_off", agent_reply="Hi"),
        chat("INT6", days=2, action=None))


def test_every_breakdown_sums_to_the_same_total():
    result = pilot.numbers(mixed(), NOW)
    assert result["total"] == 6
    for name in ("days", "markets", "actions", "intents"):
        assert sum(r["chats"] for r in result[name]) == 6, name
        assert sum(r["resolved"] for r in result[name]) == result["resolved"], name
    assert result["resolved"] == 3


def test_a_market_of_none_is_its_own_row_last():
    markets = pilot.numbers(mixed(), NOW)["markets"]
    assert [(r["key"], r["chats"]) for r in markets] == [("DE", 1), ("US", 4), (None, 1)]


def test_unclassified_and_missing_action_are_rows_not_gaps():
    result = pilot.numbers(mixed(), NOW)
    assert result["unclassified"] == 1
    assert {"key": None, "chats": 1, "resolved": 1} in result["intents"]
    assert {"key": None, "chats": 1, "resolved": 0} in result["actions"]


def test_criterion_uses_order_status_chats_only():
    criterion = pilot.numbers(mixed(), NOW)["criterion"]
    assert (criterion["chats"], criterion["resolved"], criterion["rate"], criterion["target"]) == (3, 1, 1 / 3, 0.5)


def test_a_row_without_tokens_is_unpriced_not_free():
    cost = pilot.numbers(mixed(), NOW)["cost"]
    assert (cost["priced"], cost["unpriced"]) == (5, 1)
    one = (1000 * 2.0 + 100 * 10.0) / 1_000_000
    assert cost["total"] == pytest.approx(5 * one)
    assert cost["per_chat"] == pytest.approx(one)
    assert cost["priced_resolved"] == 2 and cost["per_resolved_chat"] == pytest.approx(one)
    assert cost["input_tokens"] == 5000 and cost["output_tokens"] == 500


def test_checked_sample_takes_the_latest_mark_per_chat():
    store = mixed()
    store.mark("INT1", "marco", "same", now=T0)
    store.mark("INT1", "lena", "wrong", sounded_sure=True, now=T0 + timedelta(hours=1))
    store.mark("INT2", "marco", "wrong", now=T0)
    store.mark("INT3", "marco", "better", now=T0)
    store.mark("INT3", "marco", "worse", now=T0 + timedelta(hours=2))
    checked = pilot.numbers(store, NOW)["checked"]
    assert checked == {"sample": 3, "verdicts": {"same": 0, "better": 0, "worse": 1, "wrong": 2}, "confidently_wrong": 1}


def test_an_empty_store_gives_zeros_and_no_division_error():
    result = pilot.numbers(FakeShadowStore(), NOW)
    assert result["total"] == 0 and result["resolved"] == 0
    assert result["days"] == result["markets"] == result["actions"] == result["intents"] == []
    assert result["criterion"]["rate"] is None
    assert result["checked"] == {"sample": 0, "verdicts": {"same": 0, "better": 0, "worse": 0, "wrong": 0},
                                 "confidently_wrong": 0}
    cost = pilot.numbers(FakeShadowStore(), NOW)["cost"]
    assert cost["per_chat"] is None and cost["per_resolved_chat"] is None and cost["total"] == 0


def test_baseline_constants_are_in_the_result():
    assert pilot.numbers(FakeShadowStore(), NOW)["baseline"] == {
        "person_cost": 7.0, "person_minutes": 4, "product_cost": 0.99, "success_rate": 0.5}


def test_the_numbers_are_identical_on_two_calls():
    store = mixed()
    store.mark("INT1", "marco", "same", now=T0)
    assert pilot.numbers(store, NOW) == pilot.numbers(store, NOW)


def test_wilson_interval():
    low, high = pilot.wilson(8, 10)
    assert (round(low, 3), round(high, 3)) == (0.490, 0.943)
    assert pilot.wilson(0, 0) is None
    assert pilot.wilson(10, 10)[1] == 1.0


def test_sentences_for_a_small_fixed_case():
    store = store_with(chat("INT1"), chat("INT2", action="hand_off"), chat("INT3", intent=None))
    store.mark("INT1", "Marco", "same")
    assert pilot.sentences(pilot.numbers(store, NOW)) == [
        ("Where we are: the assistant would have resolved 1 of 2 \"where is my order\" chats (50%), against the aim of 50%. "
        "1 chats without an intent are not in this count. This is an estimate: no customer reacted in shadow mode."),
        ("Cost: a chat the assistant would have resolved costs $0.0030 in model calls (from 2 priced), against $7.00 and 4 "
        "minutes for a person and $0.99 for the ready-made product."),
        ("How sure: only 1 chats checked so far, too few to give a range (20 are needed); 1 of them were marked the same "
        "as the agent or better.")]


def test_sentences_for_an_empty_store():
    assert pilot.sentences(pilot.numbers(FakeShadowStore(), NOW)) == [
        ("Where we are: not enough yet - no \"where is my order\" chat has been classified, so there is no rate to compare "
        "with the 50% aim. This is an estimate: no customer reacted in shadow mode."),
        "Cost: not enough yet - no resolved chat has a price, so there is nothing to set against $7.00 for a person.",
        "How sure: not enough yet - no chat has been checked by a person."]


def test_sentence_with_a_big_enough_sample_gives_the_range():
    store = store_with(*[chat(f"INT{i}") for i in range(20)])
    for i in range(20):
        store.mark(f"INT{i}", "Marco", "same" if i < 16 else "wrong")
    third = pilot.sentences(pilot.numbers(store, NOW))[2]
    assert third == ("How sure: of 20 checked chats, 16 (80%) were marked the same as the agent or better; "
                     "with 95% confidence the true share is between 58% and 92%.")
