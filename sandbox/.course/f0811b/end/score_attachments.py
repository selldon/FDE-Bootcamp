"""Fifteen returns, thirty files, three runs: which fields hold?"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from attachment import read
from check_attachment import check

with open("data/attachments_truth.json") as f:
    returns = json.load(f)


def read_both(case):
    """Claude reads the invoice and the photo of one return."""
    return read(case["invoice"]) | read(case["photo"])


right = {}
start = time.time()
for attempt in [1, 2, 3]:
    with ThreadPoolExecutor(15) as pool:
        found = list(pool.map(read_both, returns))
    good = people = 0
    for case, fields in zip(returns, found):
        reasons = check(case["customer"], fields)
        decision = "ok"
        if reasons:
            decision = "person"
            people += 1
        if decision == case["decision"]:
            good += 1
        else:
            print("  wrong:", case["id"], decision, reasons)
        for name in fields:
            if str(fields[name]) == str(case["fields"][name]):
                right[name] = right.get(name, 0) + 1
    print("run", attempt, "- right decisions:", good, "of 15,",
          "to a person:", people)
for name in right:
    print("  ", name, right[name], "of 45")
print("seconds:", round(time.time() - start))
