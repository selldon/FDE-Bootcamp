"""Every few minutes: a decided task becomes an event in our queue."""
import os

import psycopg
from approvals import decided_tasks
from dotenv import load_dotenv

load_dotenv()
TABLE = """CREATE TABLE IF NOT EXISTS events (
  event_id text PRIMARY KEY,
  draft integer NOT NULL,
  approval text NOT NULL,
  done boolean NOT NULL DEFAULT false)"""
ADD = """INSERT INTO events (event_id, draft, approval)
VALUES (%s, %s, %s) ON CONFLICT (event_id) DO NOTHING"""

with psycopg.connect(os.environ["OURDB_URL"]) as db:
    db.execute(TABLE)
    new = 0
    for task in decided_tasks():
        event = task["sys_id"] + ":" + task["approval"]
        row = (event, task["u_draft"], task["approval"])
        new += db.execute(ADD, row).rowcount
    print("new events:", new)
