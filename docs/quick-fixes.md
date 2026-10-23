# Quick fixes

Code that works for now but is not the right way to do it. One line each: what, where, and why it was quick.
At the end of the prototype, each one is written again, with a test.

| What | Where | Why it was quick |
|---|---|---|
| Sessions and pending codes live in memory | `app.py` (`SESSIONS`), `verify.py` (`Verifier.pending`) | A dict was the fastest thing; a restart logs everyone out and it cannot run on more than one process. |
| Relative `data/` paths | `tools.py` (orders, carrier, `CASES`), `verify.py` (outbox) | Works only when started from the repo root; no config for the data location. |
| One `classify` call per message that `/chat` does not need for its decision | `app.py` (`chat`) | The widget wanted an `intent` field; the reply is decided by `answer`, so it costs an extra model call and delay on every message. |
| Fake email and ServiceNow: codes go to `data/outbox.jsonl`, cases to `data/cases.jsonl` | `verify.py`, `tools.py` (`open_case`) | No real mail or ServiceNow in the prototype; the files stand in for them. |
