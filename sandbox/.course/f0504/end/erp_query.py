"""One order from Ledgerline: its lines, parcels and invoice."""
from datetime import datetime

from ledgerline import connection

cursor = connection.cursor()

# what the letters mean, as the ERP owner explained them
STATUS = {"N": "new", "S": "part shipped", "F": "shipped",
          "D": "delivered", "X": "cancelled"}

ORDER = """SELECT ord_stat_cd, prom_dt, ord_tot, curr_cd
FROM ledgerline.ll_ord_hdr WHERE ord_no = :order_no"""

LINES = """SELECT l.ln_no, l.item_desc, s.trk_no, s.ship_dt
FROM ledgerline.ll_ord_ln l LEFT JOIN ledgerline.ll_shpmt s
ON s.ord_no = l.ord_no AND s.ln_no = l.ln_no
WHERE l.ord_no = :order_no ORDER BY l.ln_no"""

INVOICE = """SELECT inv_no, net_amt, tax_amt, curr_cd
FROM ledgerline.ll_inv_hdr WHERE ord_no = :order_no"""


def show_order(number):
    """One order, with the number sent as a parameter."""
    cursor.execute(ORDER, order_no=number)
    row = cursor.fetchone()
    if row is None:
        print(number, "- not found")
        return
    status, promised, total, currency = row
    print(number, STATUS[status], "promised", promised.date(),
          total, currency)
    if status != "D" and promised < datetime.now():
        print("  late by", (datetime.now() - promised).days, "days")
    cursor.execute(LINES, order_no=number)
    for line, item, tracking, shipped in cursor:
        if tracking is None:
            print(" ", line, item, "- not shipped yet")
        else:
            print(" ", line, item, "-", tracking, shipped.date())
    cursor.execute(INVOICE, order_no=number)
    for invoice, net, tax, currency in cursor:
        print("  invoice", invoice, net, "+ tax", tax, currency)


show_order("DS-20417")
show_order("DS-20417' OR '1'='1")
show_order("DS-20468")
show_order("DS-20455")
