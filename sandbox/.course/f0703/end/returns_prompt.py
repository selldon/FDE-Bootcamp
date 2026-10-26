"""Before: the return rules live in the prompt, and Claude decides."""
import json

from llm import ask

RULES = """You decide if a DemoStore customer may return an item.
The rules:
- In the UK, Germany, France and Italy: 14 days from delivery.
- In the US: 30 days from delivery, or 15 days if it was opened.
- Opened earbuds and opened software can never be returned.
- A company customer's contract decides, so a person answers.
Answer eligible, not eligible, or person.

Case: """

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"enum": ["eligible", "not eligible", "person"]},
    },
    "required": ["answer"],
    "additionalProperties": False,
}


def decide(facts):
    """Haiku reads the rules and the facts of one case, and decides."""
    reply = ask(RULES + json.dumps(facts), SCHEMA, "claude-haiku-5-5")
    return reply["answer"]
