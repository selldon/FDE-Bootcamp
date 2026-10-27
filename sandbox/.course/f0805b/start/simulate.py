"""Simulated customers: Haiku plays each profile, code checks the outcome."""
import uuid

from agent import answer
from intent import classify
from llm import ask

SIMULATOR = "claude-haiku-5-5"  # fixed: we change it only on purpose
TURNS = 10
PERSON = "A person from our team takes over this chat now."

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
