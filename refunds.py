"""The two steps of a return in the chat (B13, B15, B16, IT16).

Step 1, `prepare_return` (a model tool): reads the lines from Ledgerline, runs the rule and the money code and, if the
item can go back, keeps an offer in the context. The model supplies only the order, the line and what the customer
said about "opened"; the market, customer type, dates and money come from code.
Step 2, `confirm` (never a tool): `app.py` calls it before the model runs, when the customer's own message is a strict
yes to a pending offer. It writes the draft, creates the approval task and answers with a fixed sentence.
Nothing here moves money, and nothing the model says can write a draft.
"""
import copy
import re
from dataclasses import dataclass
from datetime import date

import oracledb

import drafts
import ledgerline
import money
import returns
import servicenow
import tools

CONFIRMED_REPLY = ("Thank you. I have sent your refund request for approval by our team. "
                   "Nothing is paid yet, and I cannot say how long the approval will take.")
FAILED_REPLY = ("I could not send your refund request, so nothing has been requested yet. "
                "Say yes to try again, or I can pass this chat to a person.")

# A yes is the whole message and one of these (decision 3). "yes but ..." is not a yes.
YES = {"yes", "y", "yes please", "please yes", "confirm", "i confirm", "yes confirm", "please confirm",
       "yes go ahead", "go ahead", "yes please go ahead", "please go ahead"}

_ledgerline = None
_drafts = None
_servicenow = None


def get_ledgerline():
    """Where the lines are read: Ledgerline, unless a test or the replay set a fake."""
    return _ledgerline or ledgerline


def get_drafts():
    """Where the draft is written: `drafts.py`, unless a test or the replay set a fake."""
    return _drafts or drafts


def get_servicenow():
    """Where the task is created: `servicenow.py`, unless a test or the replay set a fake."""
    return _servicenow or servicenow


def set_systems(ledger=None, draft_table=None, snow=None):
    global _ledgerline, _drafts, _servicenow
    _ledgerline, _drafts, _servicenow = ledger, draft_table, snow


@dataclass
class Context:
    """What a tool and the loop may know about this chat: who, which session, and the pending offer."""
    customer: str | None
    session_id: str = ""
    offer: dict | None = None  # {"order", "line", "amount", "key", "order_lines"}


def is_yes(message):
    """True only when the whole message is one of the short list of yeses."""
    words = re.sub(r"[.,!]", " ", message.lower()).split()
    return " ".join(words) in YES


def _person(reason):
    return {"decision": "person", "reason": reason}


def prepare_return(number, line, opened, ctx):
    """The decision on one line of an order, and the offer if it can go back."""
    ctx.offer = None  # a new question drops the old offer
    if ctx.customer is None:
        return {"error": "customer not verified yet"}
    if isinstance(line, bool) or not isinstance(line, int):
        return {"error": "line must be a line number"}
    if opened is not None and not isinstance(opened, bool):
        return {"error": "opened must be true, false or left out if the customer did not say"}
    try:
        order = get_ledgerline().order_lines(number, ctx.customer)
    except oracledb.Error:
        return {"error": "the order system is not available right now"}
    except ValueError:  # a code Ledgerline sent that we do not know
        return _person("unknown_data")
    header = tools.get_store().order_for_customer(number, ctx.customer)
    if order is None or header is None:
        return {"error": "no such order for this customer"}
    row = next((x for x in order["lines"] if x["line"] == line), None)
    if row is None:
        return {"error": "no such line in this order",
                "lines": [{"line": x["line"], "item": x["item"]} for x in order["lines"]]}
    if row["kind"] is None:
        return _person("unknown_product")
    delivered = ledgerline.delivery_date(row, ctx.customer, tools.get_store())
    if delivered is None:
        return {"decision": "not eligible", "reason": "not_delivered", "item": row["item"]}
    today = tools.clock().date()
    try:
        decision = returns.decide(header["market"], order["customer_type"], row["kind"],
                                  date.fromisoformat(delivered), today, opened)
        result = {"decision": decision.decision, "reason": decision.reason, "item": row["item"]}
        if decision.decision == "eligible":
            amount = money.item_refund(money.Line(row["unit_price"], row["quantity"], row["tax"]))
            result["amount"] = str(amount)
            result["currency"] = order["currency"]
            ctx.offer = {"order": number, "line": line, "amount": amount,
                         "key": drafts.idempotency_key(ctx.session_id, number, line), "order_lines": copy.deepcopy(order)}
    except (ValueError, TypeError):
        return _person("unknown_data")
    return result


def confirm(ctx):
    """Write the draft and the task for the pending offer; return the fixed sentence for the customer.

    The draft is made from the lines read when the offer was made, so its amount is the amount that was shown.
    If the draft or the task fails, the offer stays, so a re-sent yes retries: the draft and the task are found again
    by their keys, never made twice.
    """
    offer = ctx.offer
    try:
        draft = get_drafts().create(ctx.session_id, offer["order_lines"], offer["line"])
        if draft["amount"] != offer["amount"] or draft["key"] != offer["key"]:
            raise ValueError("the draft is not the offer that was shown")
        get_servicenow().create_approval_task(draft)
    except (servicenow.ServiceNowError, oracledb.Error):
        return FAILED_REPLY
    ctx.offer = None
    return CONFIRMED_REPLY
