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
