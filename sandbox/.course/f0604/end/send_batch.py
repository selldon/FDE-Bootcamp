"""Haiku names the intent of every clean chat: one batch, at half the price."""
import pandas as pd

from intent import PROMPT, SCHEMA
from llm import client

chats = pd.read_csv("data/chats_clean.csv")
requests = []
for number, transcript in zip(chats["number"], chats["transcript"]):
    message = transcript.split("\n")[0].removeprefix("Customer: ")
    requests.append({
        "custom_id": number,
        "params": {
            "model": "claude-haiku-5-5",
            "max_tokens": 1000,
            "output_config": {"effort": "low",
                              "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": PROMPT + message}],
        },
    })
batch = client.messages.batches.create(requests=requests)
with open("data/batch_id.txt", "w") as f:
    f.write(batch.id)
print(batch.id, batch.processing_status, len(requests), "chats")
