"""The middleware: the only door to Ledgerline, DemoStore's ERP."""
from datetime import date
from decimal import Decimal

import uvicorn
from approvals import open_task
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from staging import write_draft

from ledgerline import connection

app = FastAPI(title="Ledgerline middleware")
connection.call_timeout = 2000

STATUS = {"N": "new", "S": "part shipped", "F": "shipped",
          "D": "delivered", "X": "cancelled"}

ORDER_SQL = """
SELECT h.ord_stat_cd, h.prom_dt, l.item_desc, s.trk_no
FROM ledgerline.ll_ord_hdr h
JOIN ledgerline.ll_ord_ln l ON l.ord_no = h.ord_no
LEFT JOIN ledgerline.ll_shpmt s
  ON s.ord_no = l.ord_no AND s.ln_no = l.ln_no
WHERE h.ord_no = :order_no
  AND h.cust_id = :customer_id
ORDER BY l.ln_no"""


class Item(BaseModel):
    description: str
    tracking: str | None


class Order(BaseModel):
    number: str
    status: str
    promised: date
    items: list[Item]


@app.get("/orders/{number}")
def get_order(number: str, customer_id: int = Header()) -> Order:
    """One order, only for the customer who owns it."""
    cursor = connection.cursor()
    cursor.execute(ORDER_SQL, order_no=number, customer_id=customer_id)
    rows = cursor.fetchall()
    if not rows:
        raise HTTPException(404, "order not found")
    items = []
    for row in rows:
        items.append(Item(description=row[2], tracking=row[3]))
    return Order(number=number, status=STATUS[rows[0][0]],
                 promised=rows[0][1].date(), items=items)


class ReturnIn(BaseModel):
    order: str
    line: int
    amount: Decimal
    key: str


@app.post("/returns")
def create_return(body: ReturnIn, customer_id: int = Header()):
    """A refund draft in Ledgerline, and a task for a person."""
    get_order(body.order, customer_id)
    draft, new = write_draft(body.order, body.line, body.amount,
                             body.key)
    if new:
        open_task(draft, body.order, body.amount)
    return {"draft": draft}


if __name__ == "__main__":
    uvicorn.run(app, port=8001)
