"""The worker: takes each new event from the queue, once."""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
NEXT = "SELECT event_id, draft, approval FROM events WHERE NOT done"
DONE = "UPDATE events SET done = true WHERE event_id = %s"

with psycopg.connect(os.environ["OURDB_URL"]) as db:
    events = db.execute(NEXT).fetchall()
    for event, draft, approval in events:
        print("draft", draft, approval, "- tell the customer")
        db.execute(DONE, (event,))
        db.commit()
    print("handled:", len(events))
