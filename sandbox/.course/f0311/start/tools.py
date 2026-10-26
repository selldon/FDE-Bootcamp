"""Tools the agent may ask for: an order and its delivery."""
import csv
import json

with open("data/orders.json") as f:
    ORDERS = json.load(f)


def find_order(number, customer):
    """One order, only for the customer who owns it."""
    if customer is None:
        return {"error": "customer not verified yet"}
    for order in ORDERS:
        if order["number"] == number:
            if order["customer"] == customer:
                return order
    return {"error": "no such order for this customer"}


def delivery_status(tracking):
    """The carrier's last status for one parcel."""
    with open("data/carrier.csv") as f:
        for row in csv.DictReader(f):
            if row["tracking"] == tracking:
                return row
    return {"error": "no such parcel"}


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
]
