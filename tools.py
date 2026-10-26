"""Tools the agent may ask for: an order and its delivery. They read only the order store."""
from datetime import UTC, date, datetime

import checks
import store as order_store

_store = None


def get_store():
    """The order store the tools read; the real one unless a test or the replay set another."""
    global _store
    if _store is None:
        _store = order_store.Store()
    return _store


def set_store(db):
    global _store
    _store = db


def clock():
    """Now. Replaced in tests, so the age of the carrier's news is never read from the wall clock."""
    return datetime.now(UTC)


def _stale(news_date, carrier_status=None):
    """True when the carrier's last news is more than 30 hours old (IT14). No news is not stale.

    A delivered parcel's news is final, so the rule applies only to parcels that are not delivered."""
    if not news_date or carrier_status == "delivered":
        return False
    return checks.news_age(date.fromisoformat(news_date), clock()) > checks.MAX_NEWS_AGE


def find_order(number, customer):
    """One order, only for the customer who owns it."""
    if customer is None:
        return {"error": "customer not verified yet"}
    order = get_store().order_for_customer(number, customer)
    if order is None:
        return {"error": "no such order for this customer"}
    result = {k: order[k] for k in ("number", "customer", "market", "status", "items",
                                    "promised", "tracking")}
    if any(_stale(p["news_date"], p["carrier_status"]) for p in order["parcels"]):
        # The code removes the date; the prompt only says what to do with the flag.
        result["promised"] = None
        result["offer_person"] = True
    return result


def delivery_status(tracking, customer):
    """The carrier's last status for one parcel of this customer."""
    if customer is None:
        return {"error": "customer not verified yet"}
    parcel = get_store().parcel_for_customer(tracking, customer)
    if parcel is None:
        return {"error": "no such parcel"}
    result = {"tracking": parcel["tracking"], "status": parcel["carrier_status"],
              "place": parcel["place"], "date": parcel["news_date"]}
    if _stale(parcel["news_date"], parcel["carrier_status"]):
        result["date"] = None
        result["offer_person"] = True
    return result


TOOLS = [
    {
        "name": "find_order",
        "description": "One order of the customer in this chat: "
        "status, items, promised date and tracking numbers.",
        "input_schema": {
            "type": "object",
            "properties": {"number": {"type": "string"}},
            "required": ["number"],
        },
    },
    {
        "name": "delivery_status",
        "description": "The last carrier status of one parcel: "
        "where it is and the date. Needs a tracking number.",
        "input_schema": {
            "type": "object",
            "properties": {"tracking": {"type": "string"}},
            "required": ["tracking"],
        },
    },
    {
        "name": "prepare_return",
        "description": "Check whether one item of an order can be returned, and what the refund would be. "
        "Give the order number, the line number and, only if the customer said so, whether the item was opened. "
        "The decision, the reason and the amount come from our systems; this does not start a refund.",
        "input_schema": {
            "type": "object",
            "properties": {"number": {"type": "string"},
                           "line": {"type": "integer", "description": "The line number of the item in the order."},
                           "opened": {"type": ["boolean", "null"],
                                      "description": "Whether the customer said the item was opened; "
                                      "leave out if they did not say."}},
            "required": ["number", "line"],
        },
    },
    {
        "name": "policy_answer",
        "description": "Search DemoStore's policy pages (returns, warranty, delivery) for the customer's market. "
        "Give the customer's question. Give `market` only if the customer said which country they are in. "
        "Returns sections with a link, or no_page, or says the market is unknown.",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"},
                           "market": {"type": "string", "enum": ["UK", "DE", "FR", "IT", "US"],
                                      "description": "Only if the customer said their country; otherwise leave out."}},
            "required": ["question"],
        },
    },
    {
        "name": "hand_off",
        "description": "Pass the chat to a person. Use it when the "
        "customer asks for a person, is angry, or asks about "
        "anything the order tools do not cover.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string",
                                       "description": "One or two sentences for the person: the order "
                                       "number if there is one, and why. Only facts the customer wrote."},
                           "reason": {"type": "string",
                                      "enum": ["needs_human", "not_covered", "no_answer"]}},
            "required": ["summary", "reason"],
        },
    },
]
