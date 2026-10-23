# Quick fixes

Code that works for now but is not the right way to do it. One line each: what, where, and why it was quick.
At the end of the prototype, each one is written again, with a test.

| What | Where | Why it was quick |
|---|---|---|
| Sessions and pending codes live in memory | `app.py` (`SESSIONS`), `verify.py` (`Verifier.pending`) | A dict was the fastest thing; a restart logs everyone out and it cannot run on more than one process. |
| Relative `data/` paths | `tools.py` (orders, carrier, `CASES`), `verify.py` (outbox) | Works only when started from the repo root; no config for the data location. |
| `classify` is a second model call before `answer`, on every message | `app.py` (`chat`) | It now decides hand-offs, but it still runs for covered messages too, so each reply costs two model calls and extra delay. |
| Fake email and ServiceNow: codes go to `data/outbox.jsonl`, cases to `data/cases.jsonl` | `verify.py`, `tools.py` (`open_case`) | No real mail or ServiceNow in the prototype; the files stand in for them. |
| The pipeline reads all Ledgerline orders and shipments on every run | `pipeline.py`, `ledgerline.py` (Build 2) | Ledgerline has no change column (OQ-S2-1). Fine at 33 orders; with many orders the hourly full read would load the ERP in the middle of a sale. Replace with a "changed since" query once Ravi's team adds the column. |
| The intent `other` counts as covered and goes to the model | `app.py` (`COVERED`) | Greetings and follow-ups ("Which order did I ask about?") are labelled `other`; handing them off would break the chat. An uncovered question the classifier labels `other` is protected only by the system prompt (B5). |
