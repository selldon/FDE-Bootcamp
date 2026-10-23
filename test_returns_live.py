"""Live check of the return draft and its task (B15, B16, IT18, IT19, D3, D4). RUN ON REQUEST ONLY: it writes.

Writes ONE draft with a `TEST-` key into the real LL_RTN_REQ_STG (through LL_WRITER) and creates ONE real task in
ServiceNow, reads both back, then runs the same calls again and checks that nothing new appears. It creates no
`interaction` (it cannot be read back, D3). The rows stay: Ravi's team clears the `TEST-` rows (D4).
"""
import uuid

import pytest

import drafts
import ledgerline
import servicenow

pytestmark = [pytest.mark.live, pytest.mark.writes]


def test_one_draft_and_one_task_are_written_once(monkeypatch):
    key = f"TEST-{uuid.uuid4().hex[:16]}"
    monkeypatch.setattr(drafts, "idempotency_key", lambda session, order, line: key)
    shipped = next(o for o in ledgerline.all_orders() if o["tracking"])
    order = ledgerline.order_lines(shipped["number"], shipped["customer"])
    line = order["lines"][0]["line"]
    amount = drafts.refund_amount(order, line)

    draft = drafts.create("live-check", order, line)
    task = servicenow.create_approval_task(draft)
    print(f"\nDRAFT {draft}\nTASK  {task}")

    assert (draft["order"], draft["line"], draft["amount"], draft["key"]) == (order["number"], line, amount, key)
    assert draft["status"] == "W"  # we never set A or R
    assert task["u_draft"] == key
    assert servicenow.task_text(draft) in task["short_description"]
    assert servicenow.find_task(key)["sys_id"] == task["sys_id"]  # read back by u_draft

    again = drafts.create("live-check", order, line)
    task_again = servicenow.create_approval_task(again)
    assert again == draft  # the same row, read back through a new connection
    assert task_again["sys_id"] == task["sys_id"]
