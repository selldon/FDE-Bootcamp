"""The return draft (B15, B16, IT18, IT19): the only code that uses the writer account `LL_WRITER`.

One fixed `INSERT` into `LL_RTN_REQ_STG`, bind parameters only, status `W` (waiting). `REQ_ID` is made by Ledgerline, so
the insert does not name it. `REQ_KEY` is unique (D4), so a second insert with the same key is a unique violation: the
code catches exactly that error, reads the draft that is already there and returns it. It never updates a draft and
never sets any other status: only Ledgerline's own job decides a draft. The amount comes from `money.py`, never from
an argument. Nothing here moves money.
"""
import hashlib
from decimal import Decimal

import oracledb

import config
import money

WAITING = "W"
UNIQUE_VIOLATION = 1  # ORA-00001

INSERT = """
INSERT INTO LEDGERLINE.LL_RTN_REQ_STG (ORD_NO, LN_NO, RFND_AMT, REQ_KEY, STG_STAT_CD, CRT_TS)
VALUES (:order_no, :line_no, :amount, :req_key, :status, SYSTIMESTAMP)
"""

BY_KEY = """
SELECT REQ_ID, ORD_NO, LN_NO, RFND_AMT, REQ_KEY, STG_STAT_CD
FROM LEDGERLINE.LL_RTN_REQ_STG
WHERE REQ_KEY = :req_key
"""


def idempotency_key(session, order, line):
    """A sha256 hex (64 characters) of the session, the order and the line."""
    parts = [str(session), str(order), str(line)]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def is_unique_violation(error):
    """True only for ORA-00001 (the key is already there); any other database error is not."""
    if not isinstance(error, oracledb.IntegrityError) or not error.args:
        return False
    return getattr(error.args[0], "code", None) == UNIQUE_VIOLATION


def unique_violation():
    """An ORA-00001 error, as the fake raises it."""
    class Err:
        code = UNIQUE_VIOLATION
        message = "ORA-00001: unique constraint violated"
    return oracledb.IntegrityError(Err())


def refund_amount(order, line_no):
    """The refund of the first item of a line of `order_lines`' result, from `money.py`."""
    for line in order["lines"]:
        if line["line"] == line_no:
            return money.item_refund(money.Line(line["unit_price"], line["quantity"], line["tax"]))
    raise ValueError(f"order {order['number']} has no line {line_no!r}")


def _draft(row):
    req_id, order_no, line_no, amount, key, status = row
    return {"req_id": int(req_id), "order": order_no, "line": int(line_no),
            "amount": amount if isinstance(amount, Decimal) else Decimal(str(amount)),
            "key": key, "status": status.strip()}


def create(session, order, line_no, connect=oracledb.connect):
    """Write the draft of one line (or find the one a retry already wrote) and return it.

    `order` is what `ledgerline.order_lines` returned. The writer account is used here and nowhere else.
    """
    amount = refund_amount(order, line_no)
    key = idempotency_key(session, order["number"], line_no)
    binds = {"order_no": order["number"], "line_no": line_no, "amount": amount,
             "req_key": key, "status": WAITING}
    conn = connect(**config.ledgerline_writer())
    try:
        cur = conn.cursor()
        try:
            cur.execute(INSERT, binds)
            conn.commit()
        except oracledb.Error as error:
            if not is_unique_violation(error):
                raise
            conn.rollback()
        cur.execute(BY_KEY, {"req_key": key})
        rows = cur.fetchall()
        return _draft(rows[0])
    finally:
        conn.close()


class FakeDrafts:
    """The same `create` over a dict, with the columns of D2 and the same unique key."""

    def __init__(self):
        self.rows = {}  # REQ_KEY -> row
        self.next_id = 1

    def insert_row(self, order_no, line_no, amount, key, status):
        if key in self.rows:
            raise unique_violation()
        self.rows[key] = (self.next_id, order_no, line_no, amount, key, status)
        self.next_id += 1

    def create(self, session, order, line_no):
        amount = refund_amount(order, line_no)
        key = idempotency_key(session, order["number"], line_no)
        try:
            self.insert_row(order["number"], line_no, amount, key, WAITING)
        except oracledb.Error as error:
            if not is_unique_violation(error):
                raise
        return _draft(self.rows[key])
