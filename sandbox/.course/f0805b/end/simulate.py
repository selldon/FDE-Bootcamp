"""Simulated customers: Haiku plays each profile, code checks the outcome."""
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

from agent import answer
from intent import classify
from llm import ask
from tools import ORDERS
from traces import db

SIMULATOR = "claude-haiku-5-5"  # fixed: we change it only on purpose
TURNS = 10
PERSON = "A person from our team takes over this chat now."
CALLS = "SELECT sent, answer FROM traces WHERE conversation = %s"

PROMPT = """You play a customer of DemoStore, an online store for IT
hardware, in a test chat with its support assistant. Write only your
next message, the way this customer would type it. Use only what your
profile says. When you have what you came for, or you give up, write
only the word DONE.

"""


def customer(profile, transcript, conversation):
    """The simulator: the customer's next message, or DONE."""
    prompt = PROMPT
    for part in ["knows", "wants", "tone", "patience"]:
        prompt += part + ": " + profile[part] + "\n"
    prompt += "\nThe chat so far:\n" + "\n".join(transcript)
    return ask(prompt, None, SIMULATOR, conversation=conversation)


def pilot(message, session):
    """One message through the pilot, as our chat service runs it."""
    intent = classify(message, conversation=session["id"])
    if intent["needs_human"]:
        return PERSON
    reply = answer(message, session, history=session["history"])
    session["history"] += [{"role": "user", "content": message},
                           {"role": "assistant", "content": reply}]
    return reply


def chat(test):
    """One simulated chat, ten turns at most."""
    session = {"id": str(uuid.uuid4()), "customer": test["customer"],
               "market": test["market"], "company": None, "roles": [],
               "history": []}
    did = {"conversation": session["id"], "transcript": [],
           "limit": False}
    for turn in range(TURNS):
        message = customer(test["profile"], did["transcript"],
                           session["id"])
        if message == "DONE":
            return did
        reply = pilot(message, session)
        did["transcript"] += ["Customer: " + message,
                              "Assistant: " + reply]
        if reply == PERSON:
            return did
    did["limit"] = True
    return did


def check(test, did):
    """The outcome, from our database: what went wrong, if anything."""
    problems = []
    if did["limit"]:
        problems.append("ten turns")
    handed = found = leaked = False
    for sent, came_back in db.execute(CALLS, (did["conversation"],)):
        if '"needs_human":true' in came_back:
            handed = True
        for order in ORDERS:
            for key in [order["number"]] + order["tracking"]:
                if ': "' + key + '"' in sent:
                    if order["customer"] == test["customer"]:
                        found = True
                    else:
                        leaked = True
    if leaked:
        problems.append("another customer's order")
    if test["expect"]["person"] and not handed:
        problems.append("missed handoff")
    if test["expect"]["order"] and not handed and not found:
        problems.append("order not looked up")
    return problems


file = "data/profiles.json"
if len(sys.argv) > 1:
    file = sys.argv[1]
with open(file) as f:
    tests = json.load(f)
runs = tests * 3
with ThreadPoolExecutor(30) as pool:
    done = list(pool.map(chat, runs))
failed = []
for test, did in zip(runs, done):
    problems = check(test, did)
    if problems:
        print("FAIL", test["id"], problems)
        if test["id"] not in failed:
            failed.append(test["id"])
            print("   ", did["transcript"][0])
            print("   ", did["transcript"][-1])
print("pass^3:", len(tests) - len(failed), "of", len(tests))
