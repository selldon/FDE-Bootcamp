"""Look at the conversations the support team labeled."""
import json
from collections import Counter

with open("data/conversations.json") as f:
    chats = json.load(f)
print(len(chats), "labeled conversations")

intents: Counter[str] = Counter()
levels: Counter[str] = Counter()
people = 0
for chat in chats:
    intents[chat["intent"]] += 1
    levels[chat["level"]] += 1
    if chat["needs_human"]:
        people += 1

for intent, count in intents.most_common():
    print(" ", intent, count)
print(people, "need a person")
print("levels:", dict(levels))

for chat in chats:
    if chat["level"] == "hard":
        print(chat["id"], chat["message"])
        print("   ", chat["action"], "-", chat["note"])

with open("data/held_out.json") as f:
    held_out = json.load(f)
print(len(held_out), "held out for the final score")
