"""The pilot's numbers: the views of metrics.sql, then what they say."""
from traces import db

with open("metrics.sql") as f:
    db.execute(f.read())

ENDED = """SELECT left(last_reply, 60) FROM chats
WHERE NOT handed ORDER BY started"""
for (reply,) in db.execute(ENDED):
    print(reply)

OUTCOMES = """SELECT outcome, count(*) FROM outcomes
GROUP BY outcome ORDER BY count(*) DESC"""
for outcome, count in db.execute(OUTCOMES):
    print(count, outcome)
