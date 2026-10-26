"""Replay the 40 labeled conversations through the agent and score them."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import drafts
import kinds
import refunds
import servicenow
import tools
import traces
from agent import LINK, NO_PAGE_REPLY, OFFER_REPLY, answer

DEFAULT_CUSTOMER = "maya.ross@example.com"
# In this build the labels of later intents are a hand-off. `start_return` is a score of its own: the model made an offer,
# and so is `answer_policy` (Build 4, G4): the reply carries the link of the page the key names, or, where the key says
# "no page", it carries no link and offers a person. Hand-offs and drafts go to fakes, never to ServiceNow or the writer
# account; the replay never confirms, so it never writes. The money lines are read from the copy of Ledgerline with the
# read-only account. The policy pages are read from the real index.
LATER = {"answer_product", "check_buyer_role"}
PAGE = re.compile(r"/pages/(\d+)")


def score(label):
    """The action this build should take for a labeled action."""
    return "hand_off" if label in LATER else label


def policy_key():
    with open("data/policy_key.json") as f:
        return json.load(f)["key"]


def expected(chat, key):
    """What the chat should end in: for a policy chat the key decides (a page, or a person)."""
    if chat["action"] != "answer_policy":
        return score(chat["action"])
    return "answer_policy" if key[chat["id"]]["page"] else "offer_person"


def policy_taken(result, page):
    """A policy chat's outcome. `result.policy` means the tool ran, and then the reply's links are the tool's own."""
    pages = {m for url in LINK.findall(result.reply) for m in PAGE.findall(url)} if result.policy else set()
    if pages:
        return "answer_policy" if page in pages else "wrong_page"
    if result.action == "hand_off" or result.reply in (OFFER_REPLY, NO_PAGE_REPLY):
        return "offer_person"
    return "no_link"


def taken(action):
    """The action from code; a plain reply is a question to the customer."""
    return "ask_order_number" if action == "reply" else action


def owner(number):
    """Who owns the order, or the default customer when none is named."""
    found = tools.get_store().owner_of(number)
    return found or DEFAULT_CUSTOMER


def play(chat):
    """One conversation as a verified session of the order's owner."""
    if chat["action"] == "answer_policy":  # asked as on the site: not verified, the site sends the market (D4)
        ctx = refunds.Context(None, f"replay-{chat['id']}", market=chat["market"])
    else:
        ctx = refunds.Context(owner(chat["order_number"]), f"replay-{chat['id']}", market=chat["market"])
    token = traces.current_session.set(ctx.session_id)
    try:
        result = answer(chat["message"], ctx)
    finally:
        traces.current_session.reset(token)
    key = policy_key()
    if chat["action"] == "answer_policy":
        action = policy_taken(result, key[chat["id"]]["page"])
    else:
        action = "start_return" if ctx.offer is not None else taken(result.action)
    return {**chat, "expected": expected(chat, key), "taken": action, "reply": result.reply}


def main():
    fake_drafts, snow = drafts.FakeDrafts(), servicenow.FakeServiceNow()
    traces.set_sink(traces.FakeTraces())  # the replay writes no rows into the real table
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
    policy = [r for r in runs if r["action"] == "answer_policy"]
    print(f"Policy conversations: {sum(r['taken'] == r['expected'] for r in policy)} of {len(policy)} (right link, or no link and a person)")
    stayed = [r for r in runs
              if r["needs_human"] and r["taken"] != "hand_off"]
    print(f"Drafts written: {len(fake_drafts.rows)} (must be 0); tasks: {len(snow.tasks)}; cases (fake): {len(snow.cases)}")
    print(f"Needed a person but stayed with the assistant: {len(stayed)}")
    for r in stayed:
        print(f"  {r['id']}: {r['message']}\n    -> {r['reply']}")


if __name__ == "__main__":
    main()
