"""The last calls to Claude, and what each conversation cost."""
from traces import db

LAST = """SELECT left(conversation, 8), model, input_tokens,
  output_tokens, cost, ms, left(answer, 30)
FROM traces ORDER BY id DESC LIMIT 6"""
TOTALS = """SELECT left(conversation, 8), count(*), sum(cost), sum(ms)
FROM traces GROUP BY conversation ORDER BY max(id) DESC LIMIT 3"""

for row in db.execute(LAST):
    print(*row)
print("per conversation: calls, dollars, milliseconds")
for row in db.execute(TOTALS):
    print(*row)
