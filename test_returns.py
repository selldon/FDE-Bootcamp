"""Fast tests of the return rule (B12, IT15, goal G3). Pure code: no model, no database, no network.

These tests are the spec of `returns.py`, which is written by hand. They pin this shape:

    returns.decide(market, customer_type, product, delivered, today, opened)
        market         "UK" | "DE" | "FR" | "IT" | "US"
        customer_type  "consumer" | "business"
        product        "earbuds" | "software" | "other"   (the kind, from the SKU mapping of Phase 4)
        delivered      datetime.date, the day it was delivered (day 0)
        today          datetime.date, an argument: the rule never reads the clock
        opened         True | False | None   (None = the customer was not asked yet)
    -> an object with .decision ("eligible" | "not eligible" | "person" | "ask opened") and .reason
    returns.REASONS    the fixed set of reason codes

Errors are ValueError and name the bad value. Names and reason codes are the first guess: change them in both files
if you want others, as long as each test still says the same thing.
"""
import ast
import json
import random
from datetime import date, timedelta

import pytest

import returns

DELIVERED = date(2026, 10, 1)
WINDOWS = {"UK": 14, "DE": 14, "FR": 14, "IT": 14, "US": 30}
EU_UK = ["UK", "DE", "FR", "IT"]


def day(n):
    """`today` for a return made n days after the delivery day."""
    return DELIVERED + timedelta(days=n)


def decide(market="UK", customer_type="consumer", product="other", n=5, opened=False, delivered=DELIVERED):
    return returns.decide(market=market, customer_type=customer_type, product=product,
                          delivered=delivered, today=delivered + timedelta(days=n), opened=opened)


def kind(name):
    return name if name in ("earbuds", "software") else "other"


def from_case(case):
    facts = case["facts"]
    return returns.decide(
        market=facts["market"],
        customer_type="business" if facts["business"] else "consumer",
        product=kind(facts["product"]),
        delivered=date.fromisoformat(facts["delivered"]),
        today=date.fromisoformat(facts["today"]),
        opened=facts["opened"])


with open("data/borderline_returns.json") as f:
    BORDERLINE = json.load(f)


# T1 - the 30 borderline cases (B12, G3)
@pytest.mark.parametrize("case", BORDERLINE, ids=[c["id"] for c in BORDERLINE])
def test_t1_borderline_case_gets_the_right_decision(case):
    assert from_case(case).decision == case["right"]


# T2 - UK, DE, FR, IT: day 14 yes, day 15 no (B12)
@pytest.mark.parametrize("market", EU_UK)
def test_t2_eu_and_uk_window_is_14_days_and_the_last_day_counts(market):
    assert decide(market, n=13).decision == "eligible"
    assert decide(market, n=14).decision == "eligible"
    assert decide(market, n=15).decision == "not eligible"
    assert decide(market, n=0).decision == "eligible"


# T3 - in the UK and the EU opening does not shorten the window (B12)
@pytest.mark.parametrize("market", EU_UK)
def test_t3_opened_does_not_shorten_the_eu_and_uk_window(market):
    assert decide(market, n=13, opened=True).decision == "eligible"
    assert decide(market, n=14, opened=True).decision == "eligible"
    assert decide(market, n=15, opened=True).decision == "not eligible"


# T4 - US unopened: 30 days (B12)
def test_t4_us_unopened_window_is_30_days():
    assert decide("US", n=30, opened=False).decision == "eligible"
    assert decide("US", n=31, opened=False).decision == "not eligible"
    assert decide("US", n=14, opened=False).decision == "eligible"


# T5 - US opened: 15 days (B12)
def test_t5_us_opened_window_is_15_days():
    assert decide("US", n=15, opened=True).decision == "eligible"
    assert decide("US", n=16, opened=True).decision == "not eligible"
    assert decide("US", n=20, opened=True).decision == "not eligible"
    assert decide("US", n=20, opened=False).decision == "eligible"


# T6 - opened earbuds never; unopened earbuds follow the market window (B12)
@pytest.mark.parametrize("market", list(WINDOWS))
def test_t6_opened_earbuds_are_never_returned(market):
    for n in (0, 1, 10):
        assert decide(market, product="earbuds", n=n, opened=True).decision == "not eligible"


@pytest.mark.parametrize("market", list(WINDOWS))
def test_t6_unopened_earbuds_follow_the_market_window(market):
    window = WINDOWS[market]
    assert decide(market, product="earbuds", n=window, opened=False).decision == "eligible"
    assert decide(market, product="earbuds", n=window + 1, opened=False).decision == "not eligible"


# T7 - opened software never; unopened software follows the window (B12)
@pytest.mark.parametrize("market", list(WINDOWS))
def test_t7_opened_software_is_never_returned(market):
    for n in (0, 1, 10):
        assert decide(market, product="software", n=n, opened=True).decision == "not eligible"


@pytest.mark.parametrize("market", list(WINDOWS))
def test_t7_unopened_software_follows_the_market_window(market):
    window = WINDOWS[market]
    assert decide(market, product="software", n=window, opened=False).decision == "eligible"
    assert decide(market, product="software", n=window + 1, opened=False).decision == "not eligible"


# T8 - a DemoStore Business customer always goes to a person (B12)
@pytest.mark.parametrize("market", list(WINDOWS))
@pytest.mark.parametrize("product", ["other", "earbuds", "software"])
@pytest.mark.parametrize("n", [0, 14, 15, 30, 31, 90])
@pytest.mark.parametrize("opened", [True, False, None])
def test_t8_business_is_always_a_person(market, product, n, opened):
    assert decide(market, "business", product, n, opened).decision == "person"


# T9 - the window comes from the market only; an unknown market is an error (B12)
@pytest.mark.parametrize("market", list(WINDOWS))
def test_t9_every_known_market_is_decided(market):
    assert decide(market, n=1).decision == "eligible"


@pytest.mark.parametrize("market", ["CA", "uk", "", None, "Germany"])
def test_t9_an_unknown_market_is_an_error_that_names_it(market):
    with pytest.raises(ValueError) as error:
        decide(market)
    assert repr(market) in str(error.value) or str(market) in str(error.value)


# T10 - an unknown customer type or product kind is an error (B12)
@pytest.mark.parametrize("customer_type", ["C", "B", "company", "", None])
def test_t10_an_unknown_customer_type_is_an_error_that_names_it(customer_type):
    with pytest.raises(ValueError) as error:
        decide(customer_type=customer_type)
    assert str(customer_type) in str(error.value)


@pytest.mark.parametrize("product", ["laptop", "toaster", "", None])
def test_t10_an_unknown_product_kind_is_an_error_that_names_it(product):
    with pytest.raises(ValueError) as error:
        decide(product=product)
    assert str(product) in str(error.value)


# T11 - no delivery date, or a return before the delivery, is an error and never "eligible" (B12)
def test_t11_not_delivered_yet_is_an_error():
    with pytest.raises(ValueError):
        returns.decide(market="UK", customer_type="consumer", product="other",
                       delivered=None, today=day(3), opened=False)


def test_t11_today_before_the_delivery_is_an_error():
    with pytest.raises(ValueError):
        returns.decide(market="UK", customer_type="consumer", product="other",
                       delivered=day(3), today=day(2), opened=False)


# T12 - "opened" is asked for when it matters and ignored when it does not (B12)
def test_t12_us_between_day_16_and_30_needs_to_know_if_it_was_opened():
    result = decide("US", n=20, opened=None)
    assert result.decision == "ask opened"


@pytest.mark.parametrize("product", ["earbuds", "software"])
@pytest.mark.parametrize("market", list(WINDOWS))
def test_t12_earbuds_and_software_inside_the_window_need_to_know_if_opened(product, market):
    assert decide(market, product=product, n=5, opened=None).decision == "ask opened"


@pytest.mark.parametrize("product", ["earbuds", "software"])
def test_t12_earbuds_and_software_outside_the_window_are_decided_without_opened(product):
    assert decide("UK", product=product, n=15, opened=None).decision == "not eligible"


def test_t12_uk_laptop_does_not_need_opened():
    assert decide("UK", n=5, opened=None).decision == "eligible"
    assert decide("UK", n=20, opened=None).decision == "not eligible"


def test_t12_us_outside_every_window_does_not_need_opened():
    assert decide("US", n=31, opened=None).decision == "not eligible"


# T13 - the same inputs give the same answer, in any order (B12)
def test_t13_same_inputs_same_answer_in_any_order():
    first = [from_case(c) for c in BORDERLINE]
    shuffled = list(BORDERLINE)
    random.Random(7).shuffle(shuffled)
    by_id = {c["id"]: from_case(c) for c in shuffled}
    again = [by_id[c["id"]] for c in BORDERLINE]
    assert [(r.decision, r.reason) for r in first] == [(r.decision, r.reason) for r in again]
    assert [(r.decision, r.reason) for r in first] == [(r.decision, r.reason) for r in map(from_case, BORDERLINE)]


# T14 - every decision carries a reason from a fixed set (B12)
def test_t14_every_borderline_decision_has_a_reason_from_the_fixed_set():
    for case in BORDERLINE:
        result = from_case(case)
        assert result.reason in returns.REASONS, case["id"]


def test_t14_the_reasons_say_why():
    assert decide(n=3).reason == "within_window"
    assert decide(n=30).reason == "window_expired"
    assert decide("US", n=20, opened=True).reason == "window_expired"
    assert decide(product="earbuds", n=2, opened=True).reason == "opened_excluded"
    assert decide(product="software", n=2, opened=True).reason == "opened_excluded"
    assert decide(customer_type="business", n=30).reason == "business"


def test_t14_the_set_of_reasons_is_fixed_and_not_empty():
    assert isinstance(returns.REASONS, (set, frozenset, tuple, list))
    assert {"within_window", "window_expired", "opened_excluded", "business"} <= set(returns.REASONS)


# T15 - returns.py is pure: no model, no store, no I/O, no clock (IT15)
ALLOWED_IMPORTS = {"__future__", "dataclasses", "datetime", "enum", "typing"}


def _tree():
    with open("returns.py") as f:
        return ast.parse(f.read())


def test_t15_returns_imports_only_the_standard_library_basics():
    imported = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS


def test_t15_returns_does_no_io_and_never_reads_the_clock():
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            assert name not in {"open", "print", "input", "now", "today", "utcnow", "getenv"}, name
