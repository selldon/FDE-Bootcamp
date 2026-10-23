# Review checklist

What a person checks on every phase, before it is accepted. One line each.

- Only the phase in `docs/plan.md` was worked on, and its boxes are ticked.
- A changed decision is in `docs/spec.md` first, then in the code.
- Every new test names the B or IT line it serves.
- `python -m pytest -q -m "not live"` passes; pre-commit (ruff, mypy, fast tests, tsc) ran and was not skipped.
- A rule that must always hold is enforced in code and has a fast test, not only a sentence in the system prompt.
- Each live test touching such a rule was run three times, and the results were read.
- If the prompt, the tools or the classifier changed, `python replay.py` was run and the G1 score is recorded.
- Every model call goes through `llm.py`; the model name is the one constant there.
- No order data before the one-time code; a customer sees only her own orders; the customer ID comes from the session.
- Dates and statuses come only from a tool; nothing writes to Ledgerline outside the agreed tables.
- No tool moves money; a refund is only ever a draft that a person approves.
- A hand-off opens a case with a summary and the chat so far.
- Anything quick that is not the right way has a line in `docs/quick-fixes.md`.
- Live tests ran only on request; `data/cases.jsonl` and `.env` are not in the commit.
