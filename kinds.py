"""The product kind of a Ledgerline SKU (IT15, D1). Ledgerline has no kind column, so the kind is a mapping kept here.

UNCONFIRMED: these kinds are ours, not Marco's. OQ-S3-2 (the official kind of each SKU) is open; the replay may run on
this mapping (D5) and says so in its note. Remove this line only when Marco has answered.

The list of SKUs was read from the copy of Ledgerline on 2026-10-23 with `SELECT DISTINCT SKU_CD` (read-only). The copy
has no earbuds and no software at all, so every SKU is `other` for now. `kind` takes the SKU and nothing else: the
description (`ITEM_DESC`) is never read, because a guess from free text could refund opened earbuds.
"""
UNCONFIRMED = True

KINDS = {
    "AER-14-LAP": "other",
    "AER-14-PRO-LAP": "other",
    "DES-SPE-S2": "other",
    "DOC-STA-D2": "other",
    "GAM-HEA-H3": "other",
    "INK-PRI-P2": "other",
    "KEY-K2": "other",
    "LAS-PRI-P5": "other",
    "MOU-M3": "other",
    "NOV-24-MON": "other",
    "NOV-27-MON": "other",
    "NOV-32-MON": "other",
    "POW-SUP-850-W": "other",
    "SMA-SPE-S1": "other",
    "SSD-1-TB": "other",
    "SSD-2-TB": "other",
    "VEN-MIN-PC": "other",
    "VOL-8-GRA-CAR": "other",
    "WEB-W1": "other",
    "WI-FI-ROU-R6": "other",
}


def kind(sku):
    """`earbuds`, `software` or `other`; None for a SKU that is not in the mapping (it goes to a person)."""
    key = sku.strip() if isinstance(sku, str) else sku  # CHAR padding
    return KINDS.get(key)
