"""The hand-off (B17, IT20): a case in ServiceNow with a checked summary and the chat so far.

`open_case` is the only way the chat hands off. A case cannot be looked up (D3), so the session remembers that it
has handed off (`ctx.handed_off`): a second trigger in the same session opens nothing. The summary is written by the
model, then checked here; one that fails is replaced by a template made from code.
"""
import re

import refunds
import servicenow

HAND_OFF_REPLY = ("I have passed this to a person on our team. "
                  "They can see our chat and will take over.")
DOWN_REPLY = ("I could not pass this chat to a person just now, so nothing has been passed on. "
              "Please contact DemoStore support another way and a person will help you.")

FAILED_LIMIT = 2  # decision 6: the second failed try hands off

# reason -> (words for the template, words a summary may use to name it)
REASONS = {
    "needs_human": ("the customer asked for a person or is angry",
                    ("person", "human", "agent", "someone", "angry", "upset", "frustrat", "complain", "unhappy")),
    "failed_tries": ("two tries failed", ("fail", "twice", "unable", "could not", "unclear")),
    "not_covered": ("the question is outside what the assistant covers", ("polic", "exchange", "product", "address",
                                                                          "change", "not cover", "outside")),
    "no_answer": ("the assistant could not answer", ("could not", "no answer", "unable", "stopped")),
    "damaged": ("the item arrived damaged", ("damage", "crack", "broken", "smash", "shatter", "dent")),
}

ORDER = re.compile(r"\bDS-\d+\b", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
AMOUNT = re.compile(r"[€$£]\s?\d[\d.,]*\d|\d[\d.,]*\d?\s?(?:EUR|USD|GBP|€|\$|£)", re.IGNORECASE)


DAMAGE = re.compile(r"\b(crack\w*|broke\w*|broken|damag\w*|smash\w*|shatter\w*|dent\w*|scratch\w*)", re.IGNORECASE)
ARRIVAL = re.compile(r"\b(arriv\w*|deliver\w*|came|unbox\w*|out of the box|opened the (?:box|package|parcel))", re.IGNORECASE)


def damaged_on_arrival(history):
    """True when the customer's own words say the item came damaged: a person's case, never a refund offer (replay C25).

    Quick keyword rule (docs/quick-fixes.md): a damage word and an arrival word anywhere in what the customer wrote.
    """
    said = customer_text(history)
    return bool(DAMAGE.search(said) and ARRIVAL.search(said))


def _norm(value):
    return re.sub(r"\s+", "", value).lower()


def customer_text(history):
    """Everything the customer wrote themselves."""
    return " ".join(m["content"] for m in history if m["role"] == "user" and isinstance(m["content"], str))


def facts(text):
    """The order numbers, amounts, dates and emails in a text, normalised."""
    return {_norm(m) for rx in (ORDER, AMOUNT, DATE, EMAIL) for m in rx.findall(text)}


def summary_ok(summary, history, reason):
    """True when the summary names the order (if the customer gave one) and the reason, and invents no fact."""
    if not isinstance(summary, str) or not summary.strip():
        return False
    said = customer_text(history)
    orders = {_norm(m) for m in ORDER.findall(said)}
    if orders and not orders & {_norm(m) for m in ORDER.findall(summary)}:
        return False
    keywords = REASONS.get(reason, ("", ()))[1]
    if not any(k in summary.lower() for k in keywords):
        return False
    return facts(summary) <= facts(said)


def template_summary(history, reason, trigger):
    """A summary made only from the customer's own words and the trigger."""
    orders = sorted({m.upper() for m in ORDER.findall(customer_text(history))})
    label = REASONS.get(reason, (reason, ()))[0]
    return f"Order: {', '.join(orders) if orders else 'none given'}. Reason: {label}. Trigger: {trigger}."


def open_case(ctx, summary, history, reason, trigger):
    """Hand the chat to a person; returns the sentence for the customer.

    One case per session. If ServiceNow fails nothing was passed on, the customer is told so, and the flag stays
    unset so the next trigger tries again.
    """
    if ctx.handed_off:
        return HAND_OFF_REPLY
    if not summary_ok(summary, history, reason):
        summary = template_summary(history, reason, trigger)
    try:
        refunds.get_servicenow().create_case(summary, history, ctx.customer)
    except servicenow.ServiceNowError:
        return DOWN_REPLY
    ctx.handed_off = True
    return HAND_OFF_REPLY
