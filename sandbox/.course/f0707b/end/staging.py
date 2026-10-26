"""The only code that writes to Ledgerline: drafts in its staging table."""
import os

import oracledb
from dotenv import load_dotenv

load_dotenv()

ADD_SQL = """
INSERT INTO ledgerline.ll_rtn_req_stg
  (ord_no, ln_no, rfnd_amt, req_key)
VALUES (:order_no, :line, :amount, :key)
RETURNING req_id INTO :draft"""

FIND_SQL = """
SELECT req_id FROM ledgerline.ll_rtn_req_stg
WHERE req_key = :key"""


def write_draft(order_no, line, amount, key):
    """One draft per key: the draft, and whether it is new."""
    with oracledb.connect(
        user=os.environ["LEDGERLINE_WRITER_USER"],
        password=os.environ["LEDGERLINE_WRITER_PASSWORD"],
        dsn=os.environ["LEDGERLINE_DSN"],
    ) as connection:
        cursor = connection.cursor()
        draft = cursor.var(int)
        try:
            cursor.execute(ADD_SQL, order_no=order_no, line=line,
                           amount=amount, key=key, draft=draft)
        except oracledb.IntegrityError:
            cursor.execute(FIND_SQL, key=key)
            return cursor.fetchone()[0], False
        connection.commit()
        return draft.getvalue()[0], True
