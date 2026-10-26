"""The only code that writes to Ledgerline: drafts in its staging table."""
import os

import oracledb
from dotenv import load_dotenv

load_dotenv()

ADD_SQL = """
INSERT INTO ledgerline.ll_rtn_req_stg
  (ord_no, ln_no, rfnd_amt)
VALUES (:order_no, :line, :amount)
RETURNING req_id INTO :draft"""


def write_draft(order_no, line, amount):
    """One return draft: its number in the staging table."""
    with oracledb.connect(
        user=os.environ["LEDGERLINE_WRITER_USER"],
        password=os.environ["LEDGERLINE_WRITER_PASSWORD"],
        dsn=os.environ["LEDGERLINE_DSN"],
    ) as connection:
        cursor = connection.cursor()
        draft = cursor.var(int)
        cursor.execute(ADD_SQL, order_no=order_no, line=line,
                       amount=amount, draft=draft)
        connection.commit()
        return draft.getvalue()[0]

