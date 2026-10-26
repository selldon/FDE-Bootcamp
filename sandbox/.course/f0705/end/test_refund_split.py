"""The split follows the prices, and its shares add up to the amount."""
from decimal import Decimal

from refund_split import split


def test_three_keyboards():
    shares = split(Decimal("10.00"), [Decimal("100.00")] * 3)
    assert sum(shares) == Decimal("10.00")


def test_expensive_item_carries_more():
    shares = split(Decimal("30.00"), [Decimal("200.00"), Decimal("100.00")])
    assert shares == [Decimal("20.00"), Decimal("10.00")]
