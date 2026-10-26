"""Score the pilot: every labeled chat, three times, as a customer gets it."""
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

from agent import answer
from intent import classify
from tools import ORDERS
from traces import db

CALLS = "SELECT answer, cost FROM traces WHERE conversation = %s"
STAND_IN = "maya.ross@example.com"  # verified, for chats with no order


def pilot(chat):
    """One chat through the pilot: what it did, and what it cost."""
    session = {"id": str(uuid.uuid4()), "customer": STAND_IN,
               "market": chat["market"], "company": None, "roles": []}
    for order in ORDERS:
        if order["number"] == chat["order_number"]:
            session["customer"] = order["customer"]
    intent = classify(chat["message"], conversation=session["id"])
    reply = answer(chat["message"], session)
    did = {"person": intent["needs_human"], "looked_up": False,
           "reply": reply, "cost": 0}
    for came_back, cost in db.execute(CALLS, (session["id"],)):
        if "find_order" in came_back:
            did["looked_up"] = True
        did["cost"] += cost
    return did


def made_up_day(reply):
    """Today or tomorrow: no tool gives the date, so the model guessed it."""
    words = reply.lower().replace(".", " ").replace(",", " ").split()
    return "today" in words or "tomorrow" in words


def judge(chat, did):
    """The right action, or which mistake: from what the pilot did."""
    if chat["needs_human"] and not did["person"]:
        return "missed handoff"
    if did["person"] and not chat["needs_human"]:
        return "extra handoff"
    if did["person"]:
        return "right"
    if made_up_day(did["reply"]):
        return "confident wrong"
    if chat["action"] == "give_status" and not did["looked_up"]:
        return "wrong"
    if chat["action"] == "ask_order_number" and did["looked_up"]:
        return "wrong"
    return "right"


file = "data/conversations.json"
if len(sys.argv) > 1:
    file = sys.argv[1]
with open(file) as f:
    chats = json.load(f)
needed = 0
passed = {}
for chat in chats:
    passed[chat["id"]] = 0
    if chat["needs_human"]:
        needed += 1

confident_wrong = []
cost = 0
for run in [1, 2, 3]:
    with ThreadPoolExecutor(20) as pool:
        done = list(pool.map(pilot, chats))
    right = handed = both = 0
    for chat, did in zip(chats, done):
        verdict = judge(chat, did)
        if verdict == "right":
            right += 1
            passed[chat["id"]] += 1
        if verdict == "confident wrong":
            confident_wrong.append(chat["id"])
        if did["person"]:
            handed += 1
            if chat["needs_human"]:
                both += 1
        cost += did["cost"]
    print("run", run, "- right action:", right, "of", len(chats),
          "- handoffs: precision", both, "of", handed,
          "- recall", both, "of", needed)

pass3 = 0
for runs in passed.values():
    if runs == 3:
        pass3 += 1
print("confident wrong:", " ".join(confident_wrong))
print("pass^3:", pass3, "of", len(chats))
print("cents per conversation:", round(cost / 3 / len(chats) * 100, 2))
print("always hand off - right action:", needed, "of", len(chats),
      "- precision", needed, "of", len(chats), "- recall", needed,
      "of", needed)
