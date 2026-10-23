# DemoStore support assistant

A support chat for DemoStore, an online store for IT hardware. Python 3.12 (FastAPI), the widget in React + TypeScript.

- Build from `docs/spec.md`. The plan is `docs/plan.md`: work one phase at a time and tick its boxes.
- Run the fast tests: `python -m pytest -q -m "not live"`. Tests marked `live` call Claude; run them only when asked.
- Checks before every commit run on their own (pre-commit: ruff, mypy, the fast tests, tsc). Never skip them.
- Every model call goes through `llm.py`. The model name lives in one constant there.
- Anything quick that is not the right way goes into `docs/quick-fixes.md`.
- A refund is only ever a draft that a person approves.
- Nothing writes to Ledgerline outside the tables its owner agreed to.
