"""The return rule (B12, IT15): can this item go back? Pure code: no model, no database, no clock."""
from dataclasses import dataclass
from datetime import date

WINDOWS = {"UK": 14, "DE": 14, "FR": 14, "IT": 14, "US": 30}
US_OPENED = 15
CUSTOMER_TYPES = {"consumer", "business"}
SEALED = {"earbuds", "software"}
PRODUCTS = SEALED | {"other"}
REASONS = frozenset({"within_window", "window_expired", "opened_excluded", "business", "opened_unknown"})


@dataclass(frozen=True)
class Decision:
    decision: str
    reason: str


def _check(market, customer_type, product, delivered, today):
    if market not in WINDOWS:
        raise ValueError(f"unknown market: {market!r}")
    if customer_type not in CUSTOMER_TYPES:
        raise ValueError(f"unknown customer type: {customer_type!r}")
    if product not in PRODUCTS:
        raise ValueError(f"unknown product kind: {product!r}")
    if delivered is None:
        raise ValueError("not delivered yet: no delivery date")
    if today < delivered:
        raise ValueError(f"today {today} is before the delivery on {delivered}")


def _window(days, window):
    """Day 0 is the delivery day, and the last day of the window still counts."""
    if days <= window:
        return Decision("eligible", "within_window")
    return Decision("not eligible", "window_expired")


def decide(market, customer_type, product, delivered: date, today: date, opened):
    """Eligible, not eligible, a person, or ask whether it was opened - each with the reason why."""
    _check(market, customer_type, product, delivered, today)
    if customer_type == "business":
        return Decision("person", "business")
    days = (today - delivered).days
    window = WINDOWS[market]
    if product in SEALED:
        if opened:
            return Decision("not eligible", "opened_excluded")
        if opened is None and days <= window:
            return Decision("ask opened", "opened_unknown")
        return _window(days, window)
    if market != "US":
        return _window(days, window)
    if opened is None:
        if US_OPENED < days <= window:
            return Decision("ask opened", "opened_unknown")
        return _window(days, window)
    return _window(days, US_OPENED if opened else window)
