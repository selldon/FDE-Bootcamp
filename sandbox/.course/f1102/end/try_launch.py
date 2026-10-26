"""Two hundred test visitors, three messages each, through our split."""
from launch import db, route

TEAMS = """SELECT team, count(*), count(DISTINCT visitor) FROM launch_log
WHERE visitor LIKE 'test-%' GROUP BY team"""
BOTH = """SELECT count(*) FROM (SELECT visitor FROM launch_log
WHERE visitor LIKE 'test-%' GROUP BY visitor
HAVING count(DISTINCT team) > 1) AS mixed"""

db.execute("DELETE FROM launch_log WHERE visitor LIKE 'test-%'")
for number in range(200):
    for message in [1, 2, 3]:
        route(f"chat-{number}", f"test-{number}")
for team, messages, visitors in db.execute(TEAMS):
    print(team, "- messages:", messages, "visitors:", visitors)
print("visitors in both groups:", db.execute(BOTH).fetchone()[0])
