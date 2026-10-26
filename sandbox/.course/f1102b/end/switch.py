"""The launch from the terminal: a percent, or the kill switch off and on."""
import sys

from launch import db

value = sys.argv[1]
if value == "off":
    db.execute("UPDATE launch SET live = false")
elif value == "on":
    db.execute("UPDATE launch SET live = true")
else:
    db.execute("UPDATE launch SET percent = %s", (int(value),))
print(db.execute("SELECT percent, live FROM launch").fetchone())
