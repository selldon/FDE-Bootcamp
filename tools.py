"""Tools the agent may ask for: an order and its delivery."""
import csv
import json
from datetime import UTC, datetime

with open("data/orders.json") as f:
    ORDERS = json.load(f)


def find_order(number, customer):
    """One order, only for the customer who owns it."""
    if customer is None:
        return {"error": "customer not verified yet"}
    for order in ORDERS:
        if order["number"] == number and order["customer"] == customer:
            return order
    return {"error": "no such order for this customer"}


def delivery_status(tracking, customer):
    """The carrier's last status for one parcel of this customer."""
    if customer is None:
        return {"error": "customer not verified yet"}
    owned = any(order["customer"] == customer
                and tracking in order["tracking"] for order in ORDERS)
    if not owned:
        return {"error": "no such parcel"}
    with open("data/carrier.csv") as f:
        for row in csv.DictReader(f):
            if row["tracking"] == tracking:
                return row
    return {"error": "no such parcel"}


CASES = "data/cases.jsonl"


def open_case(summary, history, customer):
    """Open a case for a person: the summary and the chat so far."""
    case = {"opened": datetime.now(UTC).isoformat(),
            "customer": customer, "summary": summary,
            "history": list(history)}
    with open(CASES, "a") as f:
        f.write(json.dumps(case) + "\n")
    return case


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
        "name": "hand_off",
        "description": "Pass the chat to a person. Use it when the "
        "customer asks for a person, is angry, or asks about "
        "anything the order tools do not cover.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string",
                                       "description": "One or two "
                                       "sentences for the person."}},
            "required": ["summary"],
        },
    },
]
