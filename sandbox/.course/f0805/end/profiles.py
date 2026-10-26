"""Profiles for simulated customers, made from labeled old chats."""
import json
from concurrent.futures import ThreadPoolExecutor

from anthropic import transform_schema
from pydantic import BaseModel

from llm import ask
from tools import ORDERS

STAND_IN = "maya.ross@example.com"  # for chats with no order
LATER = ["answer_policy", "check_buyer_role"]


class Profile(BaseModel):
    knows: str
    wants: str
    tone: str
    patience: str


SCHEMA = transform_schema(Profile)

PROMPT = """You read an old chat message from a DemoStore customer.
Write a profile for someone who plays this customer in a test.
Write each part in one short sentence, to the customer, with "you":
what you know, what you want, your tone, and your patience.
Use only what the message and the order say. Never write what
the store should answer or do.

Message: """


def make(chat):
    """One labeled chat in, one test: the profile and what must happen."""
    prompt = PROMPT + chat["message"]
    customer = STAND_IN
    for order in ORDERS:
        if order["number"] == chat["order_number"]:
            customer = order["customer"]
            prompt += "\nThe order: " + ", ".join(order["items"])
    expect = {"person": chat["needs_human"], "order": None}
    if chat["action"] == "give_status":
        expect["order"] = chat["order_number"]
    return {"id": chat["id"], "customer": customer,
            "market": chat["market"],
            "profile": ask(prompt, SCHEMA, "claude-haiku-5-5"),
            "expect": expect}


with open("data/conversations.json") as f:
    chats = []
    for chat in json.load(f):
        if chat["action"] not in LATER:
            chats.append(chat)
with ThreadPoolExecutor(10) as pool:
    tests = list(pool.map(make, chats))
with open("data/profiles.json", "w") as f:
    json.dump(tests, f, indent=1)
print("saved", len(tests), "profiles to data/profiles.json")
