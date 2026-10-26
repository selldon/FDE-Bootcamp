"""Two days of simulated traffic for the pilot's numbers: every profile
chats once, and a customer who still needs help comes back."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

from agent import answer
from intent import classify
from llm import ask

SIMULATOR = "claude-haiku-5-5"
TURNS = 10
PERSON = "A person from our team takes over this chat now."

PROMPT = """You play a customer of DemoStore, an online store for IT
hardware, in a test chat with its support assistant. Write only your
next message, the way this customer would type it. Use only what your
profile says. When you have what you came for, or you give up, write
only the word DONE.

"""
AGAIN = """It is the next day. Below is your chat with DemoStore
yesterday. If you got what you came for, write only the word DONE.
If not, write only your first message of a new chat about the same
thing, the way this customer would type it.

"""


def customer(prompt, test, transcript):
    """The simulator: the customer's side, so it is not in a conversation."""
    for part in ["knows", "wants", "tone", "patience"]:
        prompt += part + ": " + test["profile"][part] + "\n"
    prompt += "\nThe chat so far:\n" + "\n".join(transcript)
    return ask(prompt, None, SIMULATOR).strip()


def pilot(message, session):
    """One message through the pilot, as our chat service runs it."""
    intent = classify(message, conversation=session["id"])
    if intent["needs_human"]:
        return PERSON
    reply = answer(message, session, history=session["history"])
    session["history"] += [{"role": "user", "content": message},
                           {"role": "assistant", "content": reply}]
    return reply


def chat(test, first=None):
    """One chat, ten turns at most; the transcript."""
    session = {"id": str(uuid.uuid4()), "customer": test["customer"],
               "market": test["market"], "company": None, "roles": [],
               "history": []}
    transcript = []
    for turn in range(TURNS):
        message = first or customer(PROMPT, test, transcript)
        first = None
        if message == "DONE":
            break
        reply = pilot(message, session)
        transcript += ["Customer: " + message, "Assistant: " + reply]
        if reply == PERSON:
            break
    return {"id": test["id"], "conversation": session["id"],
            "transcript": transcript}


def next_day(test, day1):
    """The same customer a day later: done, or a new chat. A chat that
    a person took over is the person's to finish, so it never comes back."""
    if not day1["transcript"] or day1["transcript"][-1].endswith(PERSON):
        return None
    message = customer(AGAIN, test, day1["transcript"])
    if message == "DONE":
        return None
    return chat(test, message)


with open("data/profiles.json") as f:
    tests = json.load(f)
with ThreadPoolExecutor(15) as pool:
    day1 = list(pool.map(chat, tests))
    day2 = list(pool.map(next_day, tests, day1))
back = [d for d in day2 if d]
with open("data/traffic.json", "w") as f:
    json.dump({"day1": day1, "day2": back}, f, indent=1)
print("day 1:", len(day1), "chats, day 2:", len(back), "came back")
