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
| The row-count check uses a fixed band of ±25% around the median of recent runs | `checks.py` (`BAND`) | One number for orders and parcels was enough for 33 rows; a sale or a slow week will trip it, and it should be set per table from real history. |
| The pipeline reads only the newest carrier file | `pipeline.py`, `carrier.py` (`newest_rows`) | Simple and enough while the nightly file holds the latest news of each parcel; if a night's file is missing or partial, news in older files is never read. |
| No lock against two pipeline runs at once | `pipeline.py` (`run`) | Each load is one transaction with upserts, so two runs end in the same data, but both read Ledgerline in full and the run record can be written twice. A lock (advisory lock in PostgreSQL) is the right way. |
| Relative `data/` paths still used by the chat's case and outbox files | `tools.py` (`CASES`), `verify.py` (outbox) | Same as the entry above; the pipeline itself needs no such path, it reads `.env` names. |
| A parcel missing from the newest carrier file gets its stored news overwritten with NULL | `pipeline.py` (`build_rows`), `store.py` (`UPSERT_PARCEL`) | Review finding 2: the upsert writes the empty news over good news, and "no news" is then not stale, so a date is given. Right way: keep the stored news when the file has none. |
| IT13 checks "parcels known" and "statuses" cannot fail in a real run | `checks.py`, `pipeline.py`, `ledgerline.py` (`all_orders`, `status_word`) | Review finding 3: orphan shipments are dropped by the join and an unknown code raises before the checks run. Right way: read the rows unjoined and let the checks see them. |
| The upsert never deletes: an order or parcel removed in Ledgerline stays in the store | `store.py`, `pipeline.py` | Review finding 4: the chat keeps serving it. Right way: remove or mark rows missing from a full read. |
| New tests do not name the B or IT line they serve | `test_carrier.py`, `test_checks.py`, `test_config.py`, `test_ledgerline.py`, `test_pipeline.py`, `test_store.py`, live tests | Review finding 5: add the line to each test. |
| Live checks of Phases 2, 3, 4 and 6 are not ticked and not run three times | `docs/plan-2.md` | Review finding 6: run them on request, read the results, tick the boxes. |
| The tools strip the carrier's news date as well as the promised date, and the plan's "Decisions to confirm" are not in the spec | `tools.py`, `docs/plan-2.md`, `docs/spec-2.md` | Review finding 7: write the decisions into `docs/spec-2.md`, then confirm them. |
| No SFTP host-key check | `carrier.py` (`connect`), `probe_live.py` | Review finding 8: the password goes to whatever answers. Right way: check the server's key against a known one. |
| The probe prints sample rows of every non-system table, masking only emails | `probe_live.py` (`ledgerline`) | Review finding 9: names and invoice data print in clear text. Right way: list columns and counts only, or mask by column. |
| The chat process imports `oracledb` through `checks` -> `ledgerline`, and `Store.owner_of` is in production code for the replay | `checks.py`, `tools.py`, `store.py` | Review finding 10: move `STATUS` to a module without drivers; move `owner_of` to the replay or tests. |
| `db.watermark()` is called in `run` and its result is dropped | `pipeline.py` (`run`) | Review finding 11: remove the call, or use the value. |
| `main()` catches only three error types; Oracle, SFTP, PostgreSQL and config errors end in a traceback | `pipeline.py` (`main`) | Review finding 12: still a non-zero exit, but no "pipeline stopped, nothing written" message. |
| The `live` marker still says "calls Claude for real" | `pyproject.toml` | Review finding 13: the new live tests call Ledgerline, SFTP and PostgreSQL; fix the wording. |
| Duplicate entry for relative `data/` paths | `docs/quick-fixes.md` | Review finding 14: merge it with the earlier row. |
| The parcel key is the tracking number alone; the same number on two orders silently keeps the last | `store.py` (`parcels`), `ledgerline.py` (`_build`) | Review finding 15: make it fail a check, or key by order and tracking. |
| Question for Ravi: order DS-20468 (replay C16) is `part shipped` in Ledgerline while both of its parcels are delivered | `docs/live-shapes.md`, `ledgerline.py` (`STATUS`) | The customer says only the router came, and the assistant hands off in both replays. Is the status stale, is a parcel marked delivered by mistake, or does `S` mean something else? Until answered the assistant cannot give a status for this order. |
