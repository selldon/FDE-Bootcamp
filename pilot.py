"""The pilot numbers: every figure the dashboard shows, from one function, so a number means the same thing every week.

Plain data in, plain data out: no model call, no HTML. Every breakdown (days, markets, actions, intents) is built
from the same list of chats, so each one sums to `total`; a missing market, action or intent is a row of its own
(key None), never dropped. Old rows without an intent or tokens stay in the totals and are counted as
"unclassified" / "unpriced".
"""
from collections import Counter
from types import SimpleNamespace

from llm import MODEL, cost

# The baseline from discovery.
PERSON_COST = 7.00        # dollars for one contact with a person
PERSON_MINUTES = 4        # minutes for one contact with a person
PRODUCT_COST = 0.99       # dollars per resolution of the ready-made product
SUCCESS_RATE = 0.5        # share of "where is my order" chats solved without a person
CRITERION_INTENT = "order_status"

# A chat counts as resolved when the gate passed and the assistant did not hand off.
RESOLVED = ("give_status", "reply", "start_return")
VERDICTS = ("same", "better", "worse", "wrong")

BASELINE = {"person_cost": PERSON_COST, "person_minutes": PERSON_MINUTES, "product_cost": PRODUCT_COST,
            "success_rate": SUCCESS_RATE}


def rate(part, whole):
    """part / whole, or None when there is nothing to divide by."""
    return part / whole if whole else None


def is_resolved(chat):
    return chat.get("action") in RESOLVED


def breakdown(chats, key):
    """[{key, chats, resolved}] for one way of grouping; a None key is its own row, last. The chats add up to the input."""
    seen, resolved = Counter(), Counter()
    for chat in chats:
        k = key(chat)
        seen[k] += 1
        resolved[k] += is_resolved(chat)
    ordered = sorted(seen, key=lambda k: (k is None, "" if k is None else str(k)))
    return [{"key": k, "chats": seen[k], "resolved": resolved[k]} for k in ordered]


def chat_cost(chat):
    """The dollar cost of one chat from its stored tokens, or None when it has none (never 0)."""
    tokens_in, tokens_out = chat.get("input_tokens"), chat.get("output_tokens")
    if tokens_in is None or tokens_out is None:
        return None
    return cost(MODEL, SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out))


def latest_marks(marks):
    """The latest mark of each chat (by `marked_at`, then name)."""
    latest = {}
    for m in marks:
        best = latest.get(m["number"])
        if best is None or (m["marked_at"], m["marker"]) > (best["marked_at"], best["marker"]):
            latest[m["number"]] = m
    return latest


def checked(marks):
    """What people said about the chats they looked at: the sample is the chats with at least one mark."""
    latest = latest_marks(marks).values()
    counts = Counter(m["verdict"] for m in latest)
    return {"sample": len(latest), "verdicts": {v: counts[v] for v in VERDICTS},
            "confidently_wrong": sum(1 for m in latest if m["verdict"] == "wrong" and m["sounded_sure"])}


def costs(chats):
    priced = [(c, chat_cost(c)) for c in chats]
    priced = [(c, p) for c, p in priced if p is not None]
    resolved = [p for c, p in priced if is_resolved(c)]
    total = sum(p for _, p in priced)
    return {"priced": len(priced), "unpriced": len(chats) - len(priced),
            "input_tokens": sum(c["input_tokens"] for c, _ in priced),
            "output_tokens": sum(c["output_tokens"] for c, _ in priced),
            "total": total, "per_chat": rate(total, len(priced)),
            "priced_resolved": len(resolved), "per_resolved_chat": rate(sum(resolved), len(resolved))}


def numbers(store, now):
    """Everything the page shows, as plain data. `now` is only stamped on the result; the same store gives the same numbers."""
    chats = store.all()
    marks = store.marks()
    in_criterion = [c for c in chats if c.get("intent") == CRITERION_INTENT]
    done = sum(is_resolved(c) for c in in_criterion)
    return {
        "as_of": now,
        "total": len(chats),
        "resolved": sum(is_resolved(c) for c in chats),
        "days": breakdown(chats, lambda c: c["opened_at"].date().isoformat()),
        "markets": breakdown(chats, lambda c: c.get("market")),
        "actions": breakdown(chats, lambda c: c.get("action")),
        "intents": breakdown(chats, lambda c: c.get("intent")),
        "unclassified": sum(1 for c in chats if c.get("intent") is None),
        "criterion": {"intent": CRITERION_INTENT, "chats": len(in_criterion), "resolved": done,
                      "rate": rate(done, len(in_criterion)), "target": SUCCESS_RATE,
                      "unclassified": sum(1 for c in chats if c.get("intent") is None)},
        "checked": checked(marks),
        "cost": costs(chats),
        "baseline": dict(BASELINE),
    }
