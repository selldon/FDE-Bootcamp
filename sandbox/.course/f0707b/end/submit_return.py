"""The chat service's side: one return the customer confirmed."""
import uuid

import httpx

URL = "http://127.0.0.1:8001/returns"
CUSTOMER = {"customer-id": "10430"}
confirmed = {"order": "DS-20531", "line": 1, "amount": "118.80",
             "key": str(uuid.uuid4())}

for timeout in (2, 30):
    try:
        reply = httpx.post(URL, json=confirmed, headers=CUSTOMER,
                           timeout=timeout)
        print(reply.json())
        break
    except httpx.TimeoutException:
        print("no answer after", timeout, "seconds: try again")
