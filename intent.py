"""What the customer wants: the shape of the answer, and classify."""
from typing import Literal

from anthropic import transform_schema
from pydantic import BaseModel

from llm import MODEL, ask


class Intent(BaseModel):
    summary: str
    intent: Literal["order_status", "return_request",
                    "policy_question", "product_question",
                    "contract_price", "other"]
    order_number: str | None
    needs_human: bool
    damaged: bool
    language: str


SCHEMA = transform_schema(Intent)

PROMPT = """You read one message from a DemoStore customer.
First explain in one sentence what the customer wants.
Then choose the intent. Copy the order number if there is one.
Set needs_human if the customer asks for a person or is angry.
Set damaged if the customer says an item came damaged or broken, in any words.
Give the language of the message as a two-letter code, like en.

Message: """


def classify(message, model=MODEL, usage=None):
    """Ask Claude what one customer message is about."""
    return ask(PROMPT + message, SCHEMA, model, usage)


# The only intents this build answers; "other" (greetings, follow-ups) still
# goes to the model, which hands off by itself when it must.
COVERED = {"order_status", "return_request", "policy_question", "other"}


def handoff_reason(intent) -> str | None:
    """Why a person must take this message (needs_human, damaged, not_covered), or None.

    One gate for the chat service and the shadow worker; the order is fixed.
    """
    if intent["needs_human"]:
        return "needs_human"
    if intent["damaged"]:
        return "damaged"
    if intent["intent"] not in COVERED:
        return "not_covered"
    return None
