"""The pilot's numbers: the views of metrics.sql, then what they say."""
from traces import db

with open("metrics.sql") as f:
    db.execute(f.read())

OUTCOMES = """SELECT outcome, count(*) FROM outcomes
GROUP BY outcome ORDER BY count(*) DESC"""
for outcome, count in db.execute(OUTCOMES):
    print(count, outcome)

REASONS = """SELECT reason, count(*) FROM outcomes
WHERE outcome = 'handed to a person'
GROUP BY reason ORDER BY count(*) DESC"""
for reason, count in db.execute(REASONS):
    print("  to a person:", reason, count)

COST = """SELECT sum(cost), count(*),
  count(*) FILTER (WHERE outcome = 'resolved') FROM outcomes"""
cost, chats, resolved = db.execute(COST).fetchone()
print("dollars per chat:", round(cost / chats, 4))
print("dollars per resolved chat:", round(cost / resolved, 4))
print("minutes back for the team:", resolved * 4)
