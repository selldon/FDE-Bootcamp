"""The same order questions: one call, or the agent?"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from agent import answer
from intent import classify
from replay import owner
from tools import delivery_status, find_order

with open("data/conversations.json") as f:
    chats = json.load(f)


def one_call(message, customer, usage):
    """Claude reads the message once; our code does the rest."""
    fields = classify(message, "claude-haiku-5-5", usage)
    if fields["needs_human"]:
        return "passed to a person"
    order = find_order(fields["order_number"], customer)
    if "error" in order:
        return order["error"]
    reply = "Order " + order["number"] + ": " + order["status"]
    for tracking in order["tracking"]:
        parcel = delivery_status(tracking, customer)
        reply += "; " + parcel["status"] + ", " + parcel["place"]
    return reply


def measure(path, chat):
    """One path on one conversation: calls, tokens, seconds."""
    customer = owner(chat["order_number"])
    usage = []
    start = time.time()
    reply = path(chat["message"], customer, usage)
    seconds = time.time() - start
    tokens = 0
    for u in usage:
        tokens += u.input_tokens + u.output_tokens
    return len(usage), tokens, seconds, reply


questions = []
for chat in chats:
    if chat["intent"] == "order_status" and chat["order_number"]:
        questions.append(chat)

for name, path in [("one call", one_call), ("agent", answer)]:
    calls = tokens = seconds = 0
    with ThreadPoolExecutor(14) as pool:
        paths = [path] * len(questions)
        for result in pool.map(measure, paths, questions):
            calls += result[0]
            tokens += result[1]
            seconds += result[2]
    print(name, "-", calls, "calls,", tokens, "tokens,",
          round(seconds / len(questions), 1), "s per question")

for chat in questions:
    if chat["needs_human"]:
        print(chat["id"], chat["message"])
        print("  one call:", measure(one_call, chat)[3])
        print("  agent:", measure(answer, chat)[3])
