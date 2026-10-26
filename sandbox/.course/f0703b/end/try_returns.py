"""One case: the code decides, then Claude explains."""
from returns import can_return, explain

laptop = {"market": "UK", "product": "laptop", "delivered": "2026-10-02",
          "today": "2026-10-22", "opened": True, "business": False}
print(can_return(laptop))
print(explain(laptop))
