"""Replay the 40 labeled conversations through the agent and score them."""
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor

import tools
from agent import answer

DEFAULT_CUSTOMER = "maya.ross@example.com"
# In this build the labels of later intents are a hand-off.
LATER = {"answer_policy", "answer_product", "start_return",
         "check_buyer_role"}


def score(label):
    """The action this build should take for a labeled action."""
    return "hand_off" if label in LATER else label


def taken(action):
    """The action from code; a plain reply is a question to the customer."""
    return "ask_order_number" if action == "reply" else action


def owner(number):
    """Who owns the order, or the default customer when none is named."""
    for order in tools.ORDERS:
        if order["number"] == number:
            return order["customer"]
    return DEFAULT_CUSTOMER


def play(chat):
    """One conversation as a verified session of the order's owner."""
    result = answer(chat["message"], owner(chat["order_number"]))
    return {**chat, "expected": score(chat["action"]),
            "taken": taken(result.action), "reply": result.reply}


def main():
    # Cases opened by the replay are not real: keep them out of data/.
    tools.CASES = tempfile.mkstemp(suffix=".jsonl")[1]
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
    print(f"Needed a person but stayed with the assistant: {len(stayed)}")
    for r in stayed:
        print(f"  {r['id']}: {r['message']}\n    -> {r['reply']}")


if __name__ == "__main__":
    main()
