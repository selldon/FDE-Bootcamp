"""Check the fields in code: first alone, then with Ledgerline."""
from decimal import Decimal

import oracledb

from ledgerline import connection

oracledb.defaults.fetch_decimals = True
cursor = connection.cursor()

INVOICE = """SELECT c.email_addr, i.inv_dt,
i.net_amt + i.tax_amt, i.curr_cd
FROM ledgerline.ll_inv_hdr i
JOIN ledgerline.ll_ord_hdr h ON h.ord_no = i.ord_no
JOIN ledgerline.ll_cust c ON c.cust_id = h.cust_id
WHERE i.ord_no = :order_no"""

ITEM = """SELECT ln_no FROM ledgerline.ll_ord_ln
WHERE ord_no = :order_no AND LOWER(item_desc) = LOWER(:item)"""


def check(customer, fields):
    """Why this return needs a person; an empty list means no reason."""
    reasons = []
    for name in fields:
        if fields[name] is None:
            reasons.append(name + " missing")
    if reasons:
        return reasons
    if fields["currency"] not in ["USD", "GBP", "EUR"]:
        reasons.append("a currency DemoStore does not use")
    if fields["product_type"] not in fields["item"].lower():
        reasons.append("the photo shows a " + fields["product_type"])
    if not fields["damage_visible"]:
        reasons.append("no damage visible")

    cursor.execute(INVOICE, order_no=fields["order_number"])
    row = cursor.fetchone()
    if row is None:
        reasons.append("order not found")
        return reasons
    email, stored_date, stored_total, stored_currency = row
    if email != customer:
        reasons.append("not this customer's order")
    if fields["invoice_date"] != str(stored_date.date()):
        reasons.append("date does not match")
    if Decimal(fields["total"]) != stored_total:
        reasons.append("total does not match")
    if fields["currency"] != stored_currency:
        reasons.append("currency does not match")
    cursor.execute(ITEM, order_no=fields["order_number"],
                   item=fields["item"])
    if cursor.fetchone() is None:
        reasons.append("item not on the order")
    return reasons
