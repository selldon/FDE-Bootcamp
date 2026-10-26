"""The finished batch: one intent per chat, the counts, and a sample for a person."""
import json
import time
from collections import Counter

import pandas as pd

from llm import client

with open("data/batch_id.txt") as f:
    batch_id = f.read()
batch = client.messages.batches.retrieve(batch_id)
while batch.processing_status != "ended":
    print(batch.processing_status, batch.request_counts.processing, "chats still waiting")
    time.sleep(30)
    batch = client.messages.batches.retrieve(batch_id)
print("ended:", batch.request_counts.succeeded, "succeeded")

intents = {}
for item in client.messages.batches.results(batch_id):
    if item.result.type == "succeeded":
        fields = json.loads(item.result.message.content[-1].text)
        intents[item.custom_id] = fields["intent"]

counts = Counter(intents.values())
for intent, count in counts.most_common():
    print(f"{intent:17} {count:5} {count / len(intents):5.0%}")

chats = pd.read_csv("data/chats_clean.csv")
chats["intent"] = chats["number"].map(intents)
other = chats[chats["intent"] == "other"]
first_lines = other["transcript"].str.split("\n").str[0]
for line, count in first_lines.value_counts().head(5).items():
    print(f"other {count:4}  {line}")

sample = chats.sample(20, random_state=7)
sample.to_csv("data/intent_sample.csv", index=False)
print("saved 20 chats for a person to check")
