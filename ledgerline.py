"""The middleware: the only code that reads Ledgerline, the ERP.

Read-only account, read-only transaction, one fixed query per question. The order
number and the customer are bind parameters, never pasted into the text. Ledgerline
has no change time on any table, so there is no "changed since" query: the pipeline
reads everything each run (spec-2, decision of 2026-10-23).
"""
from decimal import Decimal

import oracledb

import config
import kinds

# Ledgerline's letter codes -> our words. A code outside this table is an error.
STATUS = {"N": "new", "S": "part shipped", "F": "shipped",
          "D": "delivered", "X": "cancelled"}

# Ledgerline's customer-type codes -> the words returns.py uses. A code outside this table is an error.
CUSTOMER_TYPE = {"C": "consumer", "B": "business"}

ORDER = """
SELECT h.ORD_NO, LOWER(c.EMAIL_ADDR), c.MKT_CD, h.ORD_STAT_CD, h.PROM_DT
FROM LEDGERLINE.LL_ORD_HDR h
JOIN LEDGERLINE.LL_CUST c ON c.CUST_ID = h.CUST_ID
WHERE h.ORD_NO = :order_no AND LOWER(c.EMAIL_ADDR) = :customer
"""

ORDER_ITEMS = """
SELECT l.ORD_NO, l.ITEM_DESC
FROM LEDGERLINE.LL_ORD_LN l
JOIN LEDGERLINE.LL_ORD_HDR h ON h.ORD_NO = l.ORD_NO
JOIN LEDGERLINE.LL_CUST c ON c.CUST_ID = h.CUST_ID
WHERE l.ORD_NO = :order_no AND LOWER(c.EMAIL_ADDR) = :customer
ORDER BY l.LN_NO
"""

ORDER_PARCELS = """
SELECT s.ORD_NO, s.TRK_NO, s.CARR_CD, s.SHIP_DT
FROM LEDGERLINE.LL_SHPMT s
JOIN LEDGERLINE.LL_ORD_HDR h ON h.ORD_NO = s.ORD_NO
JOIN LEDGERLINE.LL_CUST c ON c.CUST_ID = h.CUST_ID
WHERE s.ORD_NO = :order_no AND LOWER(c.EMAIL_ADDR) = :customer
ORDER BY s.LN_NO
"""

# The money of a return is read live at prepare time (decision 1), never from the hourly store.
ORDER_LINES = """
SELECT l.LN_NO, l.SKU_CD, l.ITEM_DESC, l.QTY, l.UNIT_PRC, l.TAX_AMT, h.CURR_CD, c.MKT_CD, c.CUST_TYP_CD
FROM LEDGERLINE.LL_ORD_LN l
JOIN LEDGERLINE.LL_ORD_HDR h ON h.ORD_NO = l.ORD_NO
JOIN LEDGERLINE.LL_CUST c ON c.CUST_ID = h.CUST_ID
WHERE l.ORD_NO = :order_no AND LOWER(c.EMAIL_ADDR) = :customer
ORDER BY l.LN_NO
"""

LINE_PARCELS = """
SELECT s.LN_NO, s.TRK_NO
FROM LEDGERLINE.LL_SHPMT s
JOIN LEDGERLINE.LL_ORD_HDR h ON h.ORD_NO = s.ORD_NO
JOIN LEDGERLINE.LL_CUST c ON c.CUST_ID = h.CUST_ID
WHERE s.ORD_NO = :order_no AND LOWER(c.EMAIL_ADDR) = :customer
ORDER BY s.LN_NO, s.TRK_NO
"""

ALL_ORDERS = """
SELECT h.ORD_NO, LOWER(c.EMAIL_ADDR), c.MKT_CD, h.ORD_STAT_CD, h.PROM_DT
FROM LEDGERLINE.LL_ORD_HDR h
JOIN LEDGERLINE.LL_CUST c ON c.CUST_ID = h.CUST_ID
ORDER BY h.ORD_NO
"""

ALL_ITEMS = """
SELECT ORD_NO, ITEM_DESC
FROM LEDGERLINE.LL_ORD_LN
ORDER BY ORD_NO, LN_NO
"""

ALL_PARCELS = """
SELECT ORD_NO, TRK_NO, CARR_CD, SHIP_DT
FROM LEDGERLINE.LL_SHPMT
ORDER BY ORD_NO, LN_NO
"""


def status_word(code):
    """Our word for one of Ledgerline's codes; an unknown code is an error."""
    key = code.strip() if isinstance(code, str) else code
    if key not in STATUS:
        raise ValueError(f"unknown Ledgerline status code {code!r}")
    return STATUS[key]


def customer_type_word(code):
    """Our word for Ledgerline's customer-type code; an unknown code is an error."""
    key = code.strip() if isinstance(code, str) else code
    if key not in CUSTOMER_TYPE:
        raise ValueError(f"unknown Ledgerline customer type code {code!r}")
    return CUSTOMER_TYPE[key]


def _money(value, name):
    """An amount as a Decimal (never a float, which money.py refuses)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} is not a number: {value!r}")
    return Decimal(str(value))


def _day(value):
    """A DATE column as 'YYYY-MM-DD' (or None)."""
    return value.date().isoformat() if hasattr(value, "date") else (
        value.isoformat() if value else None)


def _query(statements, connect=oracledb.connect):
    """Run fixed (sql, binds) pairs in one read-only transaction; return the rows of each."""
    conn = connect(**config.ledgerline())
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        results = []
        for sql, binds in statements:
            cur.execute(sql, binds)
            results.append(cur.fetchall())
        return results
    finally:
        conn.rollback()
        conn.close()


def _parcel(row):
    _, tracking, carrier, shipped = row
    return {"tracking": tracking, "carrier": carrier, "shipped": _day(shipped)}


def _build(header, items, parcels):
    """One order in our shape from its header row, item rows and parcel rows."""
    number, customer, market, code, promised = header
    tracking = list(dict.fromkeys(p["tracking"] for p in parcels))
    return {"number": number, "customer": customer, "market": market,
            "status": status_word(code), "items": [i[1] for i in items],
            "promised": _day(promised), "tracking": tracking,
            "parcels": list({p["tracking"]: p for p in parcels}.values())}


def order_for_customer(number, customer, connect=oracledb.connect):
    """One order, only if this customer owns it; None otherwise (as for an unknown number)."""
    binds = {"order_no": number, "customer": customer.lower()}
    headers, items, parcels = _query(
        [(ORDER, binds), (ORDER_ITEMS, binds), (ORDER_PARCELS, binds)], connect)
    if not headers:
        return None
    return _build(headers[0], items, [_parcel(r) for r in parcels])


def all_orders(connect=oracledb.connect):
    """Every order with its items and parcels (the pipeline's full read)."""
    headers, items, parcels = _query(
        [(ALL_ORDERS, {}), (ALL_ITEMS, {}), (ALL_PARCELS, {})], connect)
    return [_build(h, [i for i in items if i[0] == h[0]],
                   [_parcel(p) for p in parcels if p[0] == h[0]])
            for h in headers]


def _line(row, tracking):
    number, sku, item, quantity, price, tax, _, _, _ = row
    return {"line": int(number), "sku": sku.strip(), "item": item, "kind": kinds.kind(sku),
            "quantity": int(quantity), "unit_price": _money(price, "UNIT_PRC"),
            "tax": _money(tax, "TAX_AMT"), "tracking": tracking.get(int(number), [])}


def order_lines(number, customer, connect=oracledb.connect):
    """The lines of one order with their money, only if this customer owns it; None otherwise (as for an unknown one).

    Read live, not from the store. `kind` is None for a SKU not in `kinds` (a person decides); an unknown
    customer-type code raises. `tracking` lists the parcels of the line (empty: nothing shipped).
    """
    binds = {"order_no": number, "customer": customer.lower()}
    rows, parcels = _query([(ORDER_LINES, binds), (LINE_PARCELS, binds)], connect)
    if not rows:
        return None
    tracking = {}
    for line_no, trk in parcels:
        tracking.setdefault(int(line_no), [])
        if trk not in tracking[int(line_no)]:  # one parcel can appear twice
            tracking[int(line_no)].append(trk)
    first = rows[0]
    return {"number": number, "market": first[7], "currency": first[6].strip(),
            "customer_type": customer_type_word(first[8]),
            "lines": [_line(r, tracking) for r in rows]}


class FakeLedgerline:
    """The same `order_lines` over a dict: {order number: an order in the shape `order_lines` returns, plus 'customer'}."""

    def __init__(self, orders=None):
        self.orders = dict(orders or {})

    def order_lines(self, number, customer):
        order = self.orders.get(number)
        if order is None or order["customer"] != customer.lower():
            return None
        return {k: v for k, v in order.items() if k != "customer"}


def delivery_date(line, customer, db):
    """The day the line was delivered: the carrier's news date of its parcels in the store; None if not delivered.

    The line counts as delivered when every parcel it has is delivered, and the date is the last of them (the day the
    customer had all of it). No parcel, or any parcel not delivered, is None - never a date.
    """
    parcels = [db.parcel_for_customer(t, customer) for t in line["tracking"]]
    if not parcels or any(p is None or p["carrier_status"] != "delivered" or not p["news_date"] for p in parcels):
        return None
    return max(p["news_date"] for p in parcels)
