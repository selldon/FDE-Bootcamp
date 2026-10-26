"""The pilot's numbers: the views of metrics.sql, in one dictionary."""
from traces import db

with open("metrics.sql") as f:
    db.execute(f.read())

OUTCOMES = """SELECT outcome, count(*) FROM outcomes
GROUP BY outcome ORDER BY count(*) DESC"""

REASONS = """SELECT reason, count(*) FROM outcomes
WHERE outcome = 'handed to a person'
GROUP BY reason ORDER BY count(*) DESC"""

COST = """SELECT sum(cost), count(*),
  count(*) FILTER (WHERE outcome = 'resolved') FROM outcomes"""

ORDERS = """SELECT count(*), count(*) FILTER (WHERE outcome = 'resolved')
FROM outcomes WHERE intent = 'order_status'"""


def numbers():
    """Every number we report, from the same views every time."""
    outcomes = dict(db.execute(OUTCOMES).fetchall())
    cost, chats, resolved = db.execute(COST).fetchone()
    orders, orders_resolved = db.execute(ORDERS).fetchone()
    return {
        "chats": chats,
        "resolved": resolved,
        "handed": outcomes["handed to a person"],
        "left": outcomes["left without an answer"],
        "reasons": dict(db.execute(REASONS).fetchall()),
        "per_chat": round(float(cost) / chats, 4),
        "per_resolved": round(float(cost) / resolved, 4),
        "minutes_back": resolved * 4,
        "orders": orders,
        "orders_resolved": orders_resolved,
    }


if __name__ == "__main__":
    print(numbers())
