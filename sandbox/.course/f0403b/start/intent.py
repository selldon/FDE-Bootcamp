"""What the customer wants: the shape of the answer, and classify."""
from llm import MODEL, ask

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "intent": {
            "type": "string",
            "enum": ["order_status", "return_request",
                     "policy_question", "product_question",
                     "contract_price", "other"],
        },
        "order_number": {"type": ["string", "null"]},
        "needs_human": {"type": "boolean"},
    },
    "required": ["summary", "intent", "order_number", "needs_human"],
    "additionalProperties": False,
}

PROMPT = """You read one message from a DemoStore customer.
First explain in one sentence what the customer wants.
Then choose the intent. Copy the order number if there is one.
Set needs_human if the customer asks for a person or is angry.

Message: """


def classify(message, model=MODEL, usage=None):
    """Ask Claude what one customer message is about."""
    return ask(PROMPT + message, SCHEMA, model, usage)
