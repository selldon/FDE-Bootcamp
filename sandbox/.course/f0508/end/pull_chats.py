"""Pull the old chats from ServiceNow, page by page, into one file."""
import json
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
URL = os.environ["SERVICENOW_URL"] + "/api/now/table/interaction"
AUTH = (os.environ["SERVICENOW_USER"], os.environ["SERVICENOW_PASSWORD"])
LIMIT = 100


def get_page(offset):
    """One page of chats, the oldest first, and the total."""
    params = {"sysparm_limit": LIMIT, "sysparm_offset": offset,
              "sysparm_query": "ORDERBYopened_at"}
    for attempt in [1, 2, 3, 4, 5]:
        response = httpx.get(URL, params=params, auth=AUTH)
        if response.status_code != 429:
            break
        wait = int(response.headers["Retry-After"])
        print(f"429 at offset {offset}: waiting {wait} s")
        time.sleep(wait)
    response.raise_for_status()
    return response.json()["result"], int(response.headers["X-Total-Count"])


chats = {}
if os.path.exists("data/chats.json"):
    with open("data/chats.json") as f:
        chats = json.load(f)
before = len(chats)

offset = 0
while True:
    page, total = get_page(offset)
    for chat in page:
        chats[chat["sys_id"]] = chat
    offset += LIMIT
    if offset >= total:
        break

with open("data/chats.json", "w") as f:
    json.dump(chats, f)
print(f"ServiceNow has {total}, we have {len(chats)}, {len(chats) - before} new")
