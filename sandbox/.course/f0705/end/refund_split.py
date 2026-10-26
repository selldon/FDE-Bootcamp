"""Splits an order amount, like an invoice's tax, across the order's items."""
import random
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
RATES = ["0.08", "0.19", "0.20", "0.22"]


def split(amount, prices):
    """One share of amount for each item, in proportion to its price."""
    total = sum(prices)
    shares = []
    for price in prices:
        share = amount * price / total
        shares.append(share.quantize(CENT, ROUND_HALF_UP))
    shares[0] += amount - sum(shares)  # the lost cent goes to the first item
    return shares


if __name__ == "__main__":
    shares = split(Decimal("10.00"), [Decimal("100.00")] * 3)
    print(*shares, "=", sum(shares))
    rng = random.Random(7)
    short = over = 0
    for _ in range(10_000):
        count = rng.randint(1, 6)
        prices = [Decimal(rng.randint(500, 50000)) / 100 for _ in range(count)]
        rate = Decimal(rng.choice(RATES))
        tax = (sum(prices) * rate).quantize(CENT, ROUND_HALF_UP)
        shares = split(tax, prices)
        if sum(shares) < tax:
            short += 1
        if sum(shares) > tax:
            over += 1
    print("of 10,000 orders:", short, "refund too little,", over, "too much")
