"""After: the return rules live in code, and Claude only explains."""
from datetime import date

from llm import ask

WINDOW = {"UK": 14, "DE": 14, "FR": 14, "IT": 14, "US": 30}
SEALED = ["earbuds", "software"]


def days_since_delivery(facts):
    """Whole days from the delivery date to today."""
    delivered = date.fromisoformat(facts["delivered"])
    today = date.fromisoformat(facts["today"])
    return (today - delivered).days


def window_for(facts):
    """How many days this customer has to return this item."""
    if facts["market"] == "US" and facts["opened"]:
        return 15
    return WINDOW[facts["market"]]


def can_return(facts):
    """Code decides: eligible, not eligible, or person."""
    if facts["business"]:
        return "person"
    if facts["opened"] and facts["product"] in SEALED:
        return "not eligible"
    if days_since_delivery(facts) <= window_for(facts):
        return "eligible"
    return "not eligible"


def explain(facts):
    """Claude puts the decision of the code into words, nothing more."""
    prompt = ("Tell a DemoStore customer in two short sentences what "
              "this return decision means. Use only these facts.\n")
    prompt += "Decision: " + can_return(facts) + "\n"
    prompt += "Product: " + facts["product"] + "\n"
    prompt += "Days since delivery: " + str(days_since_delivery(facts)) + "\n"
    prompt += "Return window: " + str(window_for(facts)) + " days"
    return ask(prompt, None, "claude-haiku-5-5")
