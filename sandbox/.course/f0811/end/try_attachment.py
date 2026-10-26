"""Three returns: Claude reads their files, our code checks them."""
import json

from attachment import read
from check_attachment import check

with open("data/attachments_truth.json") as f:
    returns = json.load(f)

for case in returns:
    if case["id"] in ["r10", "r12", "r13"]:
        fields = read(case["invoice"]) | read(case["photo"])
        print(case["id"], list(fields.values()))
        print("   ", check(case["customer"], fields))
