"""Who meets the assistant: a share of visitors, set in our database."""
import hashlib

from traces import db

db.execute("""CREATE TABLE IF NOT EXISTS launch (
  percent integer NOT NULL,
  live boolean NOT NULL)""")
if db.execute("SELECT count(*) FROM launch").fetchone()[0] == 0:
    db.execute("INSERT INTO launch VALUES (5, true)")
db.execute("""CREATE TABLE IF NOT EXISTS launch_log (
  at timestamptz NOT NULL DEFAULT now(),
  conversation text NOT NULL,
  visitor text NOT NULL,
  team text NOT NULL)""")


def route(conversation, visitor):
    """Assistant or control for one message, written down either way."""
    percent, live = db.execute("SELECT percent, live FROM launch").fetchone()
    bucket = int(hashlib.sha256(visitor.encode()).hexdigest(), 16) % 100
    team = "control"
    if live and bucket < percent:
        team = "assistant"
    db.execute("INSERT INTO launch_log (conversation, visitor, team) "
               "VALUES (%s, %s, %s)", (conversation, visitor, team))
    return team
