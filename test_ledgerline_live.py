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


def test_the_lines_of_one_known_order_add_up_to_its_total():
    from decimal import Decimal

    order = next(o for o in ledgerline.all_orders() if o["tracking"])
    lines = ledgerline.order_lines(order["number"], order["customer"])
    assert lines and lines["lines"] and lines["currency"] and lines["customer_type"] in ledgerline.CUSTOMER_TYPE.values()
    sql = "SELECT ORD_TOT FROM LEDGERLINE.LL_ORD_HDR WHERE ORD_NO = :order_no"
    total = ledgerline._query([(sql, {"order_no": order["number"]})])[0][0][0]
    paid = sum(line["unit_price"] * line["quantity"] + line["tax"] for line in lines["lines"])
    assert paid == Decimal(str(total))
