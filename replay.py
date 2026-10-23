"""Replay the 40 labeled conversations through the agent and score them."""
import json
from concurrent.futures import ThreadPoolExecutor

import drafts
import kinds
import refunds
import servicenow
import tools
from agent import answer

DEFAULT_CUSTOMER = "maya.ross@example.com"
# In this build the labels of later intents are a hand-off. `start_return` is a score of its own: the model made an offer.
# Hand-offs and drafts go to fakes, never to ServiceNow or the writer account; the replay never confirms, so it
# never writes. The money lines are read from the copy of Ledgerline with the read-only account.
LATER = {"answer_policy", "answer_product", "check_buyer_role"}


def score(label):
    """The action this build should take for a labeled action."""
    return "hand_off" if label in LATER else label


def taken(action):
    """The action from code; a plain reply is a question to the customer."""
    return "ask_order_number" if action == "reply" else action


def owner(number):
    """Who owns the order, or the default customer when none is named."""
    found = tools.get_store().owner_of(number)
    return found or DEFAULT_CUSTOMER


def play(chat):
    """One conversation as a verified session of the order's owner."""
    ctx = refunds.Context(owner(chat["order_number"]), f"replay-{chat['id']}")
    result = answer(chat["message"], ctx)
    action = "start_return" if ctx.offer is not None else taken(result.action)
    return {**chat, "expected": score(chat["action"]), "taken": action, "reply": result.reply}


def main():
    fake_drafts, snow = drafts.FakeDrafts(), servicenow.FakeServiceNow()
    refunds.set_systems(None, fake_drafts, snow)  # Ledgerline stays the real, read-only copy
    if kinds.UNCONFIRMED:
        print("Note: the SKU kinds (kinds.py) are UNCONFIRMED - OQ-S3-2 is open (Marco); the replay runs on that mapping (D5).\n")
    with open("data/conversations.json") as f:
        chats = json.load(f)
    with ThreadPoolExecutor(20) as pool:
        runs = list(pool.map(play, chats))
    for run in runs:
        mark = "ok  " if run["taken"] == run["expected"] else "MISS"
        print(f"{mark} {run['id']} expected {run['expected']:<16} "
              f"taken {run['taken']}")
    right = sum(r["taken"] == r["expected"] for r in runs)
    print(f"\nScore: {right} of {len(runs)}")
    stayed = [r for r in runs
              if r["needs_human"] and r["taken"] != "hand_off"]
    print(f"Drafts written: {len(fake_drafts.rows)} (must be 0); tasks: {len(snow.tasks)}; cases (fake): {len(snow.cases)}")
    print(f"Needed a person but stayed with the assistant: {len(stayed)}")
    for r in stayed:
        print(f"  {r['id']}: {r['message']}\n    -> {r['reply']}")


if __name__ == "__main__":
    main()
