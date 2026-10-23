"""Live check: reads one known order from the real copy of Ledgerline. Run on request."""
import pytest

import ledgerline

pytestmark = pytest.mark.live


def test_one_known_order_from_the_copy():
    orders = ledgerline.all_orders()
    shipped = next(o for o in orders if o["tracking"])  # an order with parcels
    order = ledgerline.order_for_customer(shipped["number"], shipped["customer"])
    assert order is not None
    assert order["status"] in ledgerline.STATUS.values()
    assert order["promised"] and order["parcels"]
    assert ledgerline.order_for_customer(shipped["number"], "nobody@example.invalid") is None
