"""One question, the way the chat service asks it."""
import uuid

from agent import answer
from intent import classify

session = {"id": uuid.uuid4().hex[:8], "customer": None, "history": []}
question = "Where is my order DS-20417?"
print("conversation", session["id"])
print(classify(question, conversation=session["id"])["intent"])
usage = []
print(answer(question, session, usage=usage))
print("the agent asked Claude", len(usage), "times")
