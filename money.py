"""The refund amount (B14, IT17). Pure code on `Decimal`: no model, no database, no I/O, nothing here moves money.

A line has a unit price, a quantity and the tax of the whole line (Ledgerline: `UNIT_PRC`, `QTY`, `TAX_AMT`). A refund
for one item is its share of the price plus its share of the tax.

Rounding: there is no half-up or half-even anywhere. Amounts are whole cents, and a split is done in whole cents: every
item gets the amount divided by the number of items rounded down to the cent, and what is left over (the cents the
division could not place) goes to the first item. So the shares always add up to the line, cent for cent. An amount
with more than two decimals, a negative amount or a `float` is an error, never rounded or guessed.
"""
from dataclasses import dataclass
from decimal import Decimal

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Line:
    unit_price: Decimal
    quantity: int
    tax: Decimal  # the tax of all units of the line


def _cents(value, name) -> int:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, not {type(value).__name__}")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a non-negative amount: {value!r}")
    cents = value * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"{name} has more than two decimals: {value!r}")
    return int(cents)


def _quantity(quantity) -> int:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise TypeError(f"quantity must be an int, not {type(quantity).__name__}")
    if quantity < 1:
        raise ValueError(f"quantity must be at least 1: {quantity!r}")
    return quantity


def _split(total_cents: int, parts: int) -> list[int]:
    base, left = divmod(total_cents, parts)
    return [base + left] + [base] * (parts - 1)


def _money(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2).quantize(CENT)


def line_total(line: Line) -> Decimal:
    """What the customer paid for the whole line: price of all units plus its tax."""
    quantity = _quantity(line.quantity)
    return _money(_cents(line.unit_price, "unit_price") * quantity + _cents(line.tax, "tax"))


def item_refunds(line: Line) -> list[Decimal]:
    """The refund of each item of the line, first item first. They add up to `line_total(line)`."""
    quantity = _quantity(line.quantity)
    prices = _split(_cents(line.unit_price, "unit_price") * quantity, quantity)
    taxes = _split(_cents(line.tax, "tax"), quantity)
    return [_money(p + t) for p, t in zip(prices, taxes)]


def item_refund(line: Line, item: int = 0) -> Decimal:
    """The refund for one item (0 is the first) of the line: its price share plus its tax share."""
    refunds = item_refunds(line)
    if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < len(refunds):
        raise ValueError(f"item must be 0..{len(refunds) - 1}: {item!r}")
    return refunds[item]
