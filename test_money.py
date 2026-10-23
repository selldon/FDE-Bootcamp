"""Fast tests of the refund amount (B14, IT17). Pure code: no model, no database, no network."""
import ast
import random
from decimal import Decimal
from pathlib import Path

import pytest

import money
from money import Line

D = Decimal


def test_refunds_of_all_items_add_up_to_what_the_customer_paid():
    rng = random.Random(17)
    for _ in range(2000):
        line = Line(D(rng.randint(0, 500_000)).scaleb(-2), rng.randint(1, 12), D(rng.randint(0, 100_000)).scaleb(-2))
        refunds = money.item_refunds(line)
        assert len(refunds) == line.quantity
        assert sum(refunds) == money.line_total(line) == line.unit_price * line.quantity + line.tax


def test_the_leftover_cent_goes_to_the_first_item():
    refunds = money.item_refunds(Line(D("10.00"), 3, D("0.01")))
    assert refunds == [D("10.01"), D("10.00"), D("10.00")]


def test_three_way_split_of_a_cent_odd_tax():
    refunds = money.item_refunds(Line(D("5.00"), 3, D("1.00")))
    assert refunds == [D("5.34"), D("5.33"), D("5.33")]
    assert sum(refunds) == D("16.00")


def test_leftover_of_two_cents_still_adds_up():
    refunds = money.item_refunds(Line(D("1.00"), 3, D("0.02")))
    assert refunds == [D("1.02"), D("1.00"), D("1.00")]


def test_one_item():
    assert money.item_refund(Line(D("49.99"), 1, D("10.00"))) == D("59.99")


def test_many_items():
    line = Line(D("19.99"), 4, D("16.00"))
    assert money.item_refunds(line) == [D("23.99")] * 4
    assert money.item_refund(line, 3) == D("23.99")


def test_zero_tax():
    assert money.item_refunds(Line(D("7.50"), 2, D("0.00"))) == [D("7.50"), D("7.50")]


def test_item_refund_defaults_to_the_first_item_and_checks_the_index():
    line = Line(D("10.00"), 3, D("0.01"))
    assert money.item_refund(line) == D("10.01")
    for bad in (-1, 3, True, 1.0):
        with pytest.raises(ValueError):
            money.item_refund(line, bad)


def test_float_raises():
    with pytest.raises(TypeError):
        money.item_refunds(Line(19.99, 1, D("0.00")))
    with pytest.raises(TypeError):
        money.item_refunds(Line(D("19.99"), 1, 1.5))
    with pytest.raises(TypeError):
        money.item_refunds(Line(D("19.99"), 1.0, D("0.00")))
    with pytest.raises(TypeError):
        money.line_total(Line(19.99, 1, D("0.00")))


def test_bad_amounts_are_errors_not_rounded():
    for line in (Line(D("1.005"), 1, D("0")), Line(D("1.00"), 1, D("0.001")), Line(D("-1.00"), 1, D("0")),
                 Line(D("1.00"), 1, D("-0.01")), Line(D("NaN"), 1, D("0")), Line(D("1.00"), 0, D("0"))):
        with pytest.raises(ValueError):
            money.item_refunds(line)


def test_the_result_is_decimal_with_two_places():
    for refund in money.item_refunds(Line(D("3"), 3, D("0.1"))) + [money.line_total(Line(D("3"), 2, D("0")))]:
        assert isinstance(refund, Decimal)
        assert refund.as_tuple().exponent == -2
    assert money.item_refunds(Line(D("3"), 3, D("0.1")))[0] == D("3.04")


def test_money_py_has_no_io_and_moves_no_money():
    tree = ast.parse(Path(money.__file__).read_text())
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"dataclasses", "decimal"}
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "float"}
    assert not any(isinstance(n, ast.Attribute) and n.attr == "float" for n in ast.walk(tree))
