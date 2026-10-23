# Build 2 - plan

Builds `docs/spec-2.md` (B7-B11, IT9-IT14, goal G2) in small phases. Each phase ends in a check we can run: the fast tests
(`python -m pytest -q -m "not live"`, also run by pre-commit with ruff, mypy, tsc), a live check against the copy of
Ledgerline, the SFTP server and our PostgreSQL (run on request), or the replay of the 40 conversations
(`python replay.py`). Tick the boxes as each task is done. One phase at a time; stop after each one.

## Where we start

Done in Build 1: `llm.py`, `intent.py`, `agent.py` (loop, hand-off, ten rounds), `app.py` (`/chat`, verify, sessions),
the widget, `verify.py`, `replay.py`, fakes in `data/`, fast tests with a scripted fake model. The packages for the new
systems are already in `requirements.txt` (`oracledb`, `psycopg`, `paramiko`); `.env.example` has the connection names.

Gaps found while reading the code (each is closed by a phase below):
- `tools.py` reads `data/orders.json` and `data/carrier.csv` at import time. Nothing reads Ledgerline, the SFTP server or
  PostgreSQL yet (B7, B8, IT9, IT10).
- No order store, no pipeline, no checks, no watermark (IT11-IT13, B11).
- `delivery_status` returns the carrier row whatever its age: no 30-hour rule (B9, IT14).
- `replay.py` finds the owner of an order through `tools.ORDERS`, the fake file; it has to ask the order store instead.
- We do not know the real shapes: the tables and columns of the Ledgerline copy, the letter codes it really uses, the
  name and layout of the carrier's file. The spec names the codes (N, S, F, D, X) but not the columns. Phase 1 looks;
  later phases are written against what it finds, and this plan is adjusted if it differs from the fakes.

Rules for the whole build:
- The fast tests use fakes and never touch the real systems. The live checks are separate, marked `live`, run on request.
- Ledgerline is read through the read-only account only. Every query is a fixed text with bind parameters; nothing writes.
- The containers (Ledgerline copy, SFTP server, PostgreSQL) are never started, stopped or changed. Our code writes only to
  the order store tables it creates itself (`CREATE TABLE IF NOT EXISTS`; no `DROP`, `TRUNCATE` or `DELETE FROM`).
  If a task ever needs one of those, a restore point comes first (`pg_dump` of the store) and the plan says so.
- `.env` is read by the code through `python-dotenv`, never opened by the agent. Secrets and customer emails are not
  printed into docs or commit messages.
- `data/conversations.json` is the only set we tune on. `data/held_out.json` was used once in Build 1 and stays closed.
- Every model call still goes through `llm.py`. New tool results hold no date that did not come from a query.

## Phase 1 - settings and a look at the real systems (read-only; groundwork for IT9, IT10, IT11)
- [x] `config.py`: one place that reads `LEDGERLINE_*`, `CARRIER_*` and `STORE_URL` from the environment; a missing name
      is an error that names the variable, not a default. `.env.example` unchanged.
- [x] `probe_live.py` (marked as a tool, not a test): Ledgerline with the read-only account in a read-only transaction -
      the tables and columns the account can see, row counts, three sample rows with the email masked; the SFTP server -
      the directory listing, the newest file name and its first lines; PostgreSQL - connects, lists existing tables.
      It makes no write of any kind.
- [x] Fast tests of `config.py` (missing variable, all present) with `monkeypatch`; no network.
- [x] Write what the probe found to `docs/live-shapes.md`: tables and columns we will read, the real letter codes, the
      carrier file name pattern and columns, the timestamp column that tells "changed since". Mark where it differs from
      `data/orders.json` and `data/carrier.csv`, and update the later phases of this plan if needed.
- [x] Check: fast tests, ruff, mypy green; `python probe_live.py` connects to all three and prints the shapes.

## Phase 2 - the middleware queries on Ledgerline (B7, B10, IT9)
Found in Phase 1 (`docs/live-shapes.md`): tables `LL_CUST`, `LL_ORD_HDR`, `LL_ORD_LN`, `LL_SHPMT`; the status column is
`ORD_STAT_CD`; **no table has a change time**, so "changed since" cannot be a timestamp query - decide (a) read all orders
every run, or (b) compare row hashes with the store, before this phase starts.
- [x] `ledgerline.py`: the only module that imports `oracledb`. The connection comes from `config.py`; the session is
      read-only. One function per question, each with one fixed SQL text: an order by number for a customer (owner check
      inside the query), all orders with their items and parcels, in one read-only transaction (no "changed since": spec-2 decided on 2026-10-23 that each run reads everything). Order number and customer
      are bind parameters, never pasted into the text.
- [x] One mapping table from Ledgerline's letter codes to our words (N new, S part shipped, F shipped, D delivered,
      X cancelled). A code outside the table raises an error that names the code; it is never guessed.
- [x] Fast tests with a fake connection: the SQL has binds and no `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `DROP`; another
      customer's order returns nothing; every code maps; an unknown code is an error.
- [ ] Check: fast tests, ruff, mypy green (done); live check (not run yet, on request) `pytest -m live test_ledgerline_live.py` reads one known order from the copy and
      the result has our status word, the promised date and the parcels.

## Phase 3 - the carrier's nightly file (B8, IT11)
Found in Phase 1: files are `upload/carrier-YYYY-MM-DD.csv`, cp1252, and the columns differ between files (a
`pickup_point` column appeared on the 22nd): read by header name with the csv module. Dates have no time of day.
- [x] `carrier.py`: the only module that imports `paramiko`. Finds the newest file on the SFTP server by the name pattern
      found in Phase 1 and parses it into rows (tracking number, status, place, date/time of the news). A bad line is
      reported with its line number, not skipped quietly.
- [x] A fake SFTP (a folder of files behind the same small interface) for the fast tests.
- [x] Fast tests: the newest of several files is chosen; a normal file parses; a file with a bad line fails loudly; an
      empty folder is an error.
- [ ] Check: fast tests green (done); live check reads the real newest file and prints the row count and the newest news time.

## Phase 4 - the order store (B7, B8, B11, IT10, IT12)
- [x] `store.py`: the tables in our PostgreSQL (`STORE_URL`) - `orders`, `parcels`, and `load_state` (the watermark and
      the row counts of recent runs) - created with `CREATE TABLE IF NOT EXISTS`. Our shape and our words.
- [x] Every write is an upsert by key (order number, tracking number): `INSERT ... ON CONFLICT ... DO UPDATE`. One load is
      one transaction.
- [x] Reads for the chat tools: an order for a customer (owner check inside the query), a parcel for a customer.
- [x] An in-memory `FakeStore` with the same interface for the fast tests of the pipeline and the tools (a dict per table).
- [x] Fast tests on the `FakeStore` contract: writing the same rows twice leaves the same store; the owner check holds.
- [ ] Check: fast tests, ruff, mypy green (done); live check (not run yet, on request) on the real PostgreSQL: create the tables, write a small batch twice, count
      rows and compare - the same both times.

## Phase 5 - the four checks (B7, B8, IT13)
- [x] `checks.py`: pure functions, each returns a list of problems: (1) the number of rows is close to a normal run
      (within a band around the recent runs; the first run has no history and only needs more than zero); (2) every
      parcel belongs to an order we know (in the batch or already in the store); (3) every status is one of ours;
      (4) the newest carrier news is recent enough.
- [x] Fast tests: for each check one batch that passes and one that fails, and the edge value of the band and of the age.
- [x] Check: fast tests green.

## Phase 6 - the hourly pipeline (B11, IT11, IT12, IT13)
- [x] `pipeline.py`: reads the watermark, fetches orders and shipments changed since it through `ledgerline.py`, reads the
      newest carrier file through `carrier.py`, builds our rows, runs the four checks, then upserts in one transaction.
      The watermark moves forward only after the checks passed and the transaction committed.
- [x] A failed check stops the load: nothing is written, the watermark stays, the exit code is not zero and the message
      names the check. The store keeps the last good data.
- [x] A command line entry (`python pipeline.py`) for the hourly run. The scheduler itself (cron line in the README) is
      Ravi's team's to install; we do not install one.
- [x] Fast tests with the fakes: a normal run fills the store; a second run with nothing new changes nothing; the same
      run twice leaves the store identical (B11); a failed check leaves the store and the watermark as they were; a crash
      in the middle of the upserts leaves no half load.
- [ ] Check: fast tests green (done); live check (not run yet, on request, `pytest -m live test_pipeline_live.py`) runs the pipeline once on the real copy and the real SFTP server, then again,
      and the store is the same after the second run.

## Phase 7 - the chat tools read the order store (B7-B10, IT10, IT14)
Found in Phase 1: the carrier's news is a date without a time, so "older than 30 hours" needs a rule (end of the news date,
or the file's own time) - decide before this phase. Parcels: `LL_SHPMT` has duplicate tracking numbers (35 rows, 33 distinct).
- [x] `find_order` and `delivery_status` read only the store; `tools.py` stops loading `data/orders.json` and
      `data/carrier.csv`. The model's tool schemas are unchanged; the customer still comes from the session.
- [x] The 30-hour rule in code: when the carrier's last news for a parcel is more than 30 hours old, the tool result has
      no delivery date and carries a flag that the reply offers a person. The age is computed from an injectable clock.
      The system prompt says what to do with the flag; the code does not rely on the prompt to hide the date.
- [x] `replay.py` finds the owner of an order through the store instead of `tools.ORDERS`.
- [x] Fast tests (re-pointed at the `FakeStore`, seeded from the existing fakes): the existing owner and unverified tests
      still pass; news at 29h59m gives the date; at 30h01m gives none and the flag; another customer's order or parcel gets
      the same error as an unknown one (B10); the dates in the reply come from the result.
- [x] Check: fast tests green; `grep -n "orders.json\|carrier.csv" *.py` finds only the seeding helper in `conftest.py`.

## Phase 8 - the replay on the copy (G2)
- [x] Run the pipeline so the store holds the copy's data; `replay.py` runs the 40 conversations against it.
      Done 2026-10-23: `python pipeline.py` loaded 33 orders, 33 parcels.
- [x] If the copy's customers or order numbers differ from the labeled conversations, say so first and adjust the mapping
      of the conversations to the copy (a note in `docs/live-shapes.md`), not the prompt.
- [x] Check: at least 36 of 40, and zero conversations that need a person stayed with the assistant. If not, stop and
      look at the misses before changing anything. One change at a time, replay after each, scores noted here.
      Result (no change made): replay on the copy scored 38 of 40; needed a person but stayed: 0. Misses: C17
      (expected give_status, asked for the order number), C26 (expected ask_order_number, handed off).

## Phase 9 - close Build 2
- [ ] `docs/quick-fixes.md`: add what was quick (candidates: fixed row-count band, one file per run, pipeline without a
      lock against two runs at once, relative paths).
- [ ] README: how to run the pipeline, how to run it again after a failure, which command is the live check.
- [ ] Check: fast tests, ruff, mypy, tsc green; final replay score written below.

## Decisions to confirm
1. Fast tests for the store use a `FakeStore` (a dict), and the upsert itself is proved by the live check on the real
   PostgreSQL. The alternative is SQLite in memory with the same SQL, which tests the SQL but needs a second placeholder style.
2. When the carrier's news is stale, the tool removes both the promised date and the carrier's date and keeps the status
   and the place; the spec says "no delivery date" and the reply offers a person.
3. "Hourly" is an entry point plus a documented cron line; no scheduler is installed by us.
4. Commits: one per phase, only when you ask (as in Build 1).
5. The agent's settings need new permissions for the probe and the live checks (`python probe_live.py`,
   `python -m pytest -m live ...`); you add them or approve at the prompt. `docker` and `sqlplus` stay denied.
