# DemoStore support assistant

A support chat for DemoStore, an online store for IT hardware. Python 3.12 (FastAPI), the widget in React + TypeScript.

- Build from `docs/spec.md`. The plan is `docs/plan.md`: work one phase at a time and tick its boxes.
- Run the fast tests: `python -m pytest -q -m "not live"`. Tests marked `live` call Claude; run them only when asked.
- Checks before every commit run on their own (pre-commit: ruff, mypy, the fast tests, tsc). Never skip them.
- Every model call goes through `llm.py`. The model name lives in one constant there.
- Anything quick that is not the right way goes into `docs/quick-fixes.md`.
- A refund is only ever a draft that a person approves.
- DemoStore's systems run in containers outside this repo: the Ledgerline copy, the carrier's SFTP server, our
  PostgreSQL, ServiceNow and Confluence. Their addresses are in `.env`. Never start, stop or change them.
- Ledgerline is read through the read-only account. The only write is a return draft into `LL_RTN_REQ_STG` through
  the writer account. Nothing else writes to Ledgerline.
