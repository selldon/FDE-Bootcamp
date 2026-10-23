# Build 3 - plan

Builds `docs/spec-3.md` (B12-B17, IT15-IT20, goal G3) in small phases. Each phase ends in a check we can run: the fast tests
(`python -m pytest -q -m "not live"`, also run by pre-commit with ruff, mypy, tsc), a read-only look at the holding table
and ServiceNow (`python probe_live.py build3`), the replay of the 40 conversations (`python replay.py`), or the one live
check that writes (Phase 10, on request). Tick the boxes as each task is done. One phase at a time; stop after each one.

## Where we start

Done in Builds 1-2: `llm.py`, `intent.py` (`return_request` is already an intent), `agent.py` (loop, two tools, `hand_off`),
`app.py` (`/chat`, verify, in-memory sessions), `ledgerline.py` (read-only), `carrier.py`, `store.py` (orders, parcels in
PostgreSQL + `FakeStore`), `pipeline.py`, `checks.py`, `replay.py`, 104 fast tests. `.env.example` already names
`LEDGERLINE_WRITER_*` and `SERVICENOW_*`; `config.py` does not read them yet.

Gaps found while reading the code (each is closed by a phase below):
- No return rule, no money code. `ledgerline.py` reads only `ITEM_DESC` of a line: **no price, tax, quantity, product kind,
  customer type or delivery date is read anywhere** (IT15, IT17). Whether Ledgerline even has them is unknown: Phase 1 looks.
- We do not know the shape of `LL_RTN_REQ_STG` (columns, unique key) or of ServiceNow's `sc_task` / `interaction` on the
  container (fields, auth, where a correlation id goes). Phase 1 looks; later phases are adjusted to what it finds.
- `tools.py` holds `find_order`, `delivery_status`, and `open_case`, which writes `data/cases.jsonl`. Tools get only the
  customer; a draft needs the session (idempotency key) and a place for the pending offer (IT16, IT19).
- `app.py` sends every `return_request` to a person (`COVERED`), and `replay.py` maps `start_return` to `hand_off` (`LATER`).
- A hand-off in the replay must never reach the real ServiceNow: the replay needs a fake sink, as it has for `CASES`.
- `.claude/settings.json` allows `python -m pytest *`, which also allows `-m live`: the one test that writes would run
  without a prompt. An `ask` rule fixes it (Phase 1).

Rules for the whole build:
- Fast tests use fakes of Ledgerline, the holding table and ServiceNow and never call Claude or touch a real system.
  Live checks are marked `live`, run on request. The check that writes is the only one, and it runs once (Phase 10).
- Ledgerline is read through `LL_READER`. The only write is one `INSERT` into `LL_RTN_REQ_STG` through `LL_WRITER`, in its own
  module (`drafts.py`), so `ledgerline.py` stays provably read-only. Fixed SQL text, bind parameters, no `UPDATE`, `DELETE`,
  `MERGE`, `DROP`, `TRUNCATE` anywhere.
- The containers (Ledgerline copy, SFTP, PostgreSQL, ServiceNow) are never started, stopped or changed. ServiceNow is
  touched by HTTP calls the build needs (one task, one case) and by read-only GETs in the probe.
- Nothing moves money: a draft has no payment field and no tool pays. Every refund is a draft a person approves.
- Dates come from a tool or the injectable clock, never from the model. The market, customer type and delivery date come
  from systems; only "was it opened" is asked from the customer.
- `.env` is read by the code through `python-dotenv`, never opened by the agent. No secrets or customer emails in docs
  or commit messages.
- `data/conversations.json` is the only set we tune on. `data/held_out.json` stays closed.
- Every model call goes through `llm.py`.
- Checkpoint (global rule): the build only adds (new files, new tables, one insert per draft, one task per draft), so no
  restore point is needed, except where a phase says so. Rows written by the live check cannot be removed by us (no
  `DELETE`): they carry a `TEST-` key so Ravi's team can find them (see Phase 10).
- Commits: one per phase, only when you ask.

## Phase 1 - settings and a read-only look at the holding table and ServiceNow (groundwork for IT15-IT20)
- [x] Save this plan as `docs/plan-3.md`.
- [x] `config.py`: `ledgerline_writer()` (same DSN, `LEDGERLINE_WRITER_USER` / `_PASSWORD`) and `servicenow()` (`SERVICENOW_URL`,
      `_USER`, `_PASSWORD`); a missing name is an error that names it. Nothing calls the writer in this phase.
- [x] Fast tests of both (all present; each missing variable named) with `monkeypatch`; no network.
- [x] `probe_live.py build3` (read-only; the existing output is unchanged): through the reader, in a read-only transaction -
      columns and types of `LL_ORD_LN`, `LL_CUST`, `LL_ORD_HDR`, `LL_SHPMT` and `LL_RTN_REQ_STG` (if the reader can see it),
      row counts, the distinct values of the code columns (market, customer type, product kind if there is one). **Names
      and counts only: no sample rows, no emails** (quick-fixes finding 9). ServiceNow - GET only: reachable, who the
      account is, the fields of `sc_task` and `interaction`, one row count each. No POST/PUT/PATCH/DELETE, no
      `LL_WRITER` login. Standard library for HTTP (no new dependency).
- [x] Fast test that `probe_live.py` has no write verb or writer account in it (a grep-style test of the file).
- [x] `pyproject.toml`: fix the `live` marker wording (quick-fixes finding 13) and add a `writes` marker for the one test
      that inserts.
- [x] `.claude/settings.json`: allow `python probe_live.py *`; add `ask` for `Bash(python -m pytest -m live*)` and
      `Bash(python -m pytest * -m live*)` so a live check never runs unprompted. `docker` and `sqlplus` stay denied.
- [x] `docs/live-shapes.md`, new section "Build 3": where price, tax, quantity, currency, product kind, customer type and
      the delivery date are (or are not); the columns and unique key of `LL_RTN_REQ_STG`; the ServiceNow fields, the
      auth, and where an idempotency / correlation id goes. Mark every difference from what Phases 2-8 assume.
- [x] Adjust Phases 2-8 of this plan to what the probe found (note the change in the phase). If a needed fact does not exist
      in Ledgerline (for example, no tax column), **stop and ask** before designing around it.
      Done: see "Found in Phase 1" under Phases 2, 3, 4, 5, 6 and 8. Three facts are missing, so we stop (below).
- [x] Check: fast tests, ruff, mypy green; `python probe_live.py build3` connects to Ledgerline and ServiceNow and prints the
      shapes; the probe wrote nothing.
      Result 2026-10-23: 123 fast tests, ruff, mypy green; the probe read Ledgerline and reached ServiceNow, and wrote nothing.

Found in Phase 1 (`docs/live-shapes.md`, "Build 3"): `LL_ORD_LN` has `QTY`, `UNIT_PRC`, `TAX_AMT`; the currency is on the order
(`CURR_CD`); `CUST_TYP_CD` is `C` or `B`. **Missing, needs your answer before the phase that uses it:**
1. Product kind (earbuds, software) is not a column; only `SKU_CD` and `ITEM_DESC`. Before Phase 4.
2. The columns and unique key of `LL_RTN_REQ_STG` are not visible to the reader. Before Phase 5.
3. `interaction` answers 401 for `fde_tasks`, and `sc_task` is empty (no field names). Before Phases 6 and 8.

Answered 2026-10-23 and written into `docs/spec-3.md` first (section 3, D1-D3; OQ-S3-2, OQ-S3-3; later D4, D5), then into the phases below:
1. D1: product kind from a mapping of `SKU_CD` in code; an unknown SKU goes to a person. OQ-S3-2 for Marco: the official kind of each SKU.
2. D2: the seven columns, listed once through `LL_WRITER` with a query that returned no rows (nothing inserted).
3. D3: `fde_tasks` creates and reads `sc_task` (`short_description`, `u_draft`); creates but cannot read `interaction` (`short_description`, `u_conversation`).

## Phase 2 - the return rule, written by a person (B12, IT15)
Changed after D1: the rule takes the product **kind** (`earbuds`, `software`, `other`); the SKU -> kind mapping and the "unknown SKU goes to a person" step live in Phase 4, not in `returns.py`. T10 stays (the rule itself raises on a kind it does not know).
Claude writes `test_returns.py` from the list below, runs it to see it fail, and stops. **You write `returns.py` by hand.**
Claude then only runs the tests and reports; it does not write or edit the rule. The phase is done when every test below
is green. The rule is a pure function: no model, no database, no clock inside (today is an argument).

Shape (the tests pin it; adjust the names when you write it): `decide(market, customer_type, product, delivered, today,
opened)` returns a decision (`eligible`, `not eligible`, `person`) and a reason code the model can put into words
(`business`, `window_expired`, `opened_excluded`, ...). Day count is calendar days from delivery, delivery day = day 0,
and the last day counts - read off the 30 cases (R02 UK 14 days: eligible; R03 UK 15 days: not).

| # | Test | Serves |
|---|---|---|
| T1 | The 30 borderline cases of `data/borderline_returns.json`, one parametrized test: decision equals `right` (`not eligible` / `eligible` / `person`) | B12, G3 |
| T2 | UK, DE, FR, IT: day 14 eligible, day 15 not (R02, R04, R06, R09 vs R03, R05, R07, R27) | B12 |
| T3 | EU/UK opened does not shorten the window: opened keyboard on day 13 is eligible (R04) | B12 |
| T4 | US unopened: day 30 eligible, day 31 not (R14 vs R15) | B12 |
| T5 | US opened: day 15 eligible, day 16 not (R12 vs R13); opened laptop on day 20 not (R10), unopened same day yes (R11) | B12 |
| T6 | Opened earbuds never, even on day 0, in every market (R17, R29); unopened earbuds follow the market window (R18) | B12 |
| T7 | Opened software never (R19); unopened software follows the window, US day 25 eligible (R20) | B12 |
| T8 | DemoStore Business is always `person`: inside the window, outside it, opened, and opened earbuds (R23-R26) - it beats `not eligible` | B12 |
| T9 | Window comes from the market only: every market in {UK, DE, FR, IT, US} is covered; an unknown market raises an error naming it, never a default | B12 |
| T10 | An unknown customer type or product kind raises an error naming it | B12 |
| T11 | A missing delivery date (not delivered yet) or a `today` before delivery is an error, never `eligible` | B12 |
| T12 | `opened` is `None` where it matters (US window, earbuds, software) -> asks for it, not a guess; where it does not matter (UK laptop) it is ignored | B12 |
| T13 | Same inputs, same answer, every time (called twice, and in any order of cases) | B12 |
| T14 | Every decision carries a reason code from a fixed set; each of the four decisions in T1 has a reason | B12 |
| T15 | `returns.py` imports nothing from `llm`, `store`, `ledgerline`, `tools`, `app` and does no I/O (a test of its imports) | IT15 |

- [x] Claude: write `test_returns.py` (T1-T15); mark it failing for the right reason (no `returns.py` yet); stop.
      Done 2026-10-23: fails at collection with `ModuleNotFoundError: No module named 'returns'`. The shape it pins is in the file's docstring.
- [x] You: write `returns.py` until T1-T15 are green.
- [x] Claude: run the tests, ruff, mypy; report. No edits to `returns.py` by Claude.
- [x] Check: T1-T15 green; fast tests, ruff, mypy green. The 30 borderline cases give the right decision.
      Result 2026-10-23: `test_returns.py` 372 passed (T1-T15 expanded by parametrize); whole fast suite 495 passed; ruff, mypy clean.

## Phase 3 - the refund amount (B14, IT17)
Found in Phase 1: tax is `TAX_AMT` per line (all units, to confirm against `ORD_TOT`), price is `UNIT_PRC`, quantity `QTY`; both are NUMBER with two decimals, currency on the order.
- [x] `money.py`: pure functions on `Decimal`. A line's price and tax, split by item (units), the cent left over goes to the
      first item; a refund for one item is its price share plus its tax share, to the cent. Rounding mode written down.
      A `float` argument raises. (Shape of a line adjusted to the Phase 1 findings.)
- [x] Fast tests: the refunds of all items of an order add up to what the customer paid (property test over many random
      lines, cent for cent); the leftover cent goes to the first item; one item, many items, zero tax, 3-way split of
      a cent-odd tax; `float` raises; the result is `Decimal` with two places; no tool or function in `money.py` moves money
      (no I/O).
- [x] Check: fast tests green.

## Phase 4 - the facts a return needs, from Ledgerline (B12, B14, IT15, IT17)
Found in Phase 1: price, tax, quantity, market (`MKT_CD`) and customer type (`CUST_TYP_CD`: C, B) exist. No product-kind column; decided in D1: a mapping of `SKU_CD` in code, unknown SKU -> a person. Delivery date still comes from the carrier news in the store.
- [x] `kinds.py`: the mapping `SKU_CD` -> `earbuds` / `software` / `other`, one dict, no guessing from `ITEM_DESC`; `kind(sku)` returns `None` for a SKU not in it, and `prepare_return` (Phase 7) turns `None` into a hand-off to a person. The list of SKUs comes from a read-only `SELECT DISTINCT SKU_CD` (names only). **The kinds are Marco's to confirm (OQ-S3-2)**: until he answers, the mapping is marked `UNCONFIRMED` in the file and the replay (Phase 9) notes it. Fast tests: every SKU in the copy is in the mapping or goes to a person; an unknown SKU gives `None`; the description is never read.
      Done 2026-10-23: 20 SKUs read from the copy (read-only `SELECT DISTINCT`); the copy has no earbuds and no software, so all 20 are `other` and `UNCONFIRMED`.
- [x] `ledgerline.py`: one fixed query `order_lines(number, customer)` (owner check inside, bind parameters): per line the
      line number, item, product kind, quantity, price, tax, currency; and the customer's type. Money read **live at
      prepare time**, not from the hourly store (decision 1). Another customer's order returns nothing, as for an unknown one.
      Done 2026-10-23: `order_lines` (`ORDER_LINES` + `LINE_PARCELS`); amounts are `Decimal`.
- [x] A mapping of Ledgerline's codes (customer type, product kind) to the words `returns.py` uses; an unknown code raises
      with the code in the message, never guessed (same rule as `STATUS`).
      Done: `CUSTOMER_TYPE` (`C`, `B`) and `customer_type_word`; the kind goes through `kinds.kind` (`None` = a person).
- [x] The delivery date of a line: the delivered parcel's news date from the store (`parcel_for_customer` / `order_for_customer`),
      through the line's parcel (`LL_SHPMT.LN_NO`). No delivered parcel -> "not delivered", not a date.
      Done: `delivery_date(line, customer, db)`; delivered only when every parcel of the line is, dated by the last one.
- [x] `FakeLedgerline` (a dict) with the same interface for the fast tests, seeded from `data/orders.json` plus prices.
- [x] Fast tests: no `INSERT`/`UPDATE`/`DELETE`/`MERGE`/`DROP` in the SQL, binds only; another customer's order is empty; every
      code maps; an unknown code is an error; a line with two parcels, a line with none.
- [x] Check: fast tests green; live read (on request) `pytest -m live test_ledgerline_live.py` reads the lines of one known
      order from the copy and the amounts add up to the order total.
      Result 2026-10-23: fast suite 551 passed, ruff and mypy clean. The live read is written (`test_ledgerline_live.py`) but not run: on request.

## Phase 5 - the draft in the holding table (B15, B16, IT18, IT19)
Found in Phase 1 and D2: `LL_RTN_REQ_STG(REQ_ID, ORD_NO, LN_NO, RFND_AMT, REQ_KEY, STG_STAT_CD, CRT_TS)`; no customer, currency or reason column. The idempotency key goes in `REQ_KEY` (64 chars: a sha256 hex). Ravi's answers (OQ-S3-3, written into the spec as D4 on 2026-10-23): `REQ_KEY` is unique, so the table keeps one draft per key; Ledgerline makes `REQ_ID` (the insert does not name it); a new draft is `STG_STAT_CD` = `W`; only Ledgerline's job sets `A` or `R`, we never do; his team clears the `TEST-` rows. Nothing blocks the insert text now.
- [x] `drafts.py`: the only code that uses `LL_WRITER`. One fixed `INSERT INTO LL_RTN_REQ_STG` with bind parameters, the
      idempotency key in `REQ_KEY`, status `W`, no `REQ_ID` in the column list (Ledgerline makes it). `idempotency_key(session, order, line)`
      is a sha256 hex of the three (64 characters). A second insert with the same key is a unique violation (D4): the code
      catches exactly that error, reads the existing draft by `REQ_KEY` (one fixed `SELECT`) and returns it; it writes nothing more.
- [x] `FakeDrafts` with the same interface (the columns of D2); the amount in a draft is a `Decimal` and comes from `money.py`, not from an argument.
- [x] Fast tests: one draft per key (the fake raises the same unique violation); a retry returns the same draft; a different line of the same order is a different
      draft; the only write statement is the one `INSERT` into `LL_RTN_REQ_STG`; no other table name in a write; `float`
      amount raises; the module has no `UPDATE`/`DELETE`/`MERGE`; the status written is `W` and the letters `A` and `R` appear
      nowhere as a value we write; the insert does not name `REQ_ID`; any other database error is raised, not swallowed.
- [x] Check: fast tests green. (The real insert is proved once, in Phase 10.)
      Result 2026-10-23: `test_drafts.py` 20 tests; whole fast suite 571 passed, ruff and mypy clean. The real insert is not run.

## Phase 6 - the approval task in ServiceNow (B15, B16, IT18, IT19)
Found in Phase 1 and D3: `fde_tasks` creates and reads `sc_task` with the fields `short_description` and `u_draft`. `u_draft` carries the draft's key (the same hash as `REQ_KEY`), so "look for a task with that key" is `GET sc_task?sysparm_query=u_draft=<key>`. The order, item and amount have no field of their own: they go into `short_description`. `interaction` can be created but not read.
- [ ] `servicenow.py`: the only code that talks to ServiceNow, over HTTP with the account from `config.py`.
      `create_approval_task(draft)` -> `sc_task`; `create_case(summary, history, customer)` -> `interaction` with `short_description` (the summary) and `u_conversation` (the chat) (used in Phase 8); it only creates, it never reads.
      The draft's key goes in `u_draft`: before creating, look for a task with that `u_draft` and return it - a retry never
      makes a second task, even if the first attempt wrote the draft and died before the task.
- [ ] `FakeServiceNow` with the same interface (records calls; can be told to fail).
- [ ] Fast tests: one task per key; a retry after "draft written, task failed" creates exactly one task; a failure raises
      a clear error and the caller sees "not created"; `short_description` has the order, item and amount and no more personal data
      than needed; `create_case` sends only `short_description` and `u_conversation` and never does a GET; no call other than the two above.
- [ ] Check: fast tests green; `python probe_live.py build3` still reaches ServiceNow.

## Phase 7 - the two steps in the chat (B13, B15, B16, IT16)
- [ ] `prepare_return(number, line, opened)` is a new tool: it reads the lines (Phase 4), runs `returns.decide` (Phase 2) and
      `money` (Phase 3), and returns the decision, the reason code and, if eligible, the item and the amount. The model
      supplies only the order, the line and what the customer said about "opened"; the market, type, dates and money
      come from code. If eligible it stores the offer (order, line, amount, key) in the session.
- [ ] **No model tool creates a draft** (decision 2). In `app.py`, before the model runs: if the session has a pending offer and
      the customer's own message is an explicit yes (a strict check in code, decision 3), the code writes the draft
      (`drafts.py`), creates the task (`servicenow.py`) and answers with a fixed sentence: the refund is waiting for
      approval, no time promised (OQ-S3-1). Any other message drops the offer.
- [ ] Tools and `answer()` get a small context (customer, session id, pending offer) instead of the bare customer; the
      existing tests are moved to it with no change in behaviour.
- [ ] System prompt: return requests use `prepare_return`; the model explains the decision, never makes one, never says the
      refund is done, never promises an exception (the code does not rely on the prompt for any of it).
- [ ] `app.py`: `return_request` goes to the model (joins `COVERED`); the session keeps the pending offer.
- [ ] Fast tests with the scripted fake model and fakes: no draft without a yes; "yes" with no pending offer does nothing;
      "yes" after a `not eligible` decision does nothing; a yes-like answer inside a longer message ("yes but...") is not a
      yes; the amount in the draft is the amount that was shown, not a number from the message or the model; two "yes"
      in a row -> one draft, one task (B16); a message re-sent after a timeout -> same draft, no second task; business
      customer -> a person; unverified customer gets nothing; the reply never says "refunded" or "done".
- [ ] Check: fast tests green.

## Phase 8 - the hand-off becomes a ServiceNow case (B17, IT20)
Found in Phase 1 and D3: `interaction` is create-only for `fde_tasks` (fields `short_description`, `u_conversation`); the 401 was the read. A case cannot be looked up, so a re-sent hand-off could open a second one: the session remembers that it has handed off (one case per session) and the code does not rely on ServiceNow for it.
- [ ] The hand-off writes an `interaction` through `servicenow.py` (`short_description` = the checked summary, `u_conversation` = the chat so far); `data/cases.jsonl` is no longer written by the chat. The
      reply to the customer is unchanged.
- [ ] Triggers in code: a request for a person and anger (`intent["needs_human"]`, already decided in `app.py`), and two failed
      tries - a counter in the session (decision 6: a failed try is a tool error or a declined/unclear reply to an offer) -
      the second one hands off without waiting for the model.
- [ ] The summary: written by the model from the chat, then checked in code - it must name the order number and the reason,
      and every order number, amount, date and email in it must appear in the customer's own messages. A summary that
      fails the check is replaced by a template summary made in code (order number, reason, trigger).
- [ ] The case carries the chat so far, as `open_case` does now. The session sets a `handed_off` flag after a case is created; a second trigger in the same session opens no second case.
- [ ] Fast tests: each of the three triggers opens one case; the second failed try opens it, the first does not; a
      summary with an invented amount or order number is replaced; a summary with the right number and reason is kept; the
      chat history is in the case; ServiceNow down -> the customer is told a person will be reached another way, not
      "passed on" (decision 7); a second trigger in the same session opens no second case; the old tests of `open_case` move to the new function.
- [ ] Check: fast tests green; no code path writes `data/cases.jsonl` (`grep -n "cases.jsonl" *.py` finds only the replay's note).

## Phase 9 - the replay (G3)
- [ ] `replay.py`: `start_return` is a score of its own, no longer `hand_off`; hand-offs and drafts go to fakes, never to the
      real ServiceNow or Ledgerline writer (the replay never confirms, so it never writes); money lines are read from the
      copy (read-only).
- [ ] Check first whether Marco has confirmed the SKU kinds (OQ-S3-2); if not, the replay runs on the `UNCONFIRMED` mapping and says so in its note.
- [ ] Run the replay on the copy; the 4 `start_return` conversations (C02, C09, C24, C28) must start a return; the other
      return conversations (C14 policy, C25 crack, C26 swap, C27 missing refund) must not draft.
- [ ] Check: at least 36 of 40; zero conversations that need a person stayed with the assistant; the 30 borderline cases
      still green. If not, stop and look at the misses before changing anything: one change at a time, replay after each,
      scores noted here. The score varies between runs (Build 2): run twice.

## Phase 10 - the live check and close Build 3
- [ ] `test_returns_live.py` (marked `live` and `writes`, run on request only, and `ask` rule from Phase 1 prompts first):
      writes **one** draft with the key `TEST-...` into the real `LL_RTN_REQ_STG` through `LL_WRITER`, creates one real task,
      reads both back (amount, order, line, status; the task by `u_draft`); creates **no** `interaction` (it cannot be read back, D3); runs the same call again and checks that the draft and the task are the
      same, not two. The rows are left in place (we cannot delete); the key tells Ravi's team what they are, and his team clears them (D4).
      The draft read back must have status `W` (we never set `A` or `R`).
- [ ] `docs/quick-fixes.md`: add what was quick (candidates: pending offer and failed-try counter in the in-memory session,
      strict yes list, template summary fallback, no timeout on ServiceNow calls, no cleanup of test rows).
- [ ] README: how to run the return flow, which command is the live check and that it writes.
- [ ] `CLAUDE.md` pointers: it still says `docs/spec.md` / `docs/plan.md`; point to `spec-3.md` / `plan-3.md` (ask first, it is your file).
- [ ] Check: fast tests, ruff, mypy, tsc green; the live check green once; final replay scores written here.

## Decisions to confirm
1. Money (price, tax) is read live from Ledgerline at prepare time, not from the hourly store; market and delivery date
   stay from the store. The alternative is to put lines into the store (stale up to an hour, one more table).
2. The draft is created by code in `app.py` after a yes, before the model runs. The model has no tool that can create one.
3. A "yes" is a strict check: the whole message is one of a short list (yes, yes please, confirm, ...). Anything else drops
   the offer. Cost: "yes but..." needs a new offer. Safe over friendly.
4. The writer lives in its own module `drafts.py`, so `ledgerline.py` stays provably read-only.
5. Phase 2: Claude writes the tests, you write `returns.py`, Claude only runs and reports.
6. "Two failed tries" = two tool errors (no such order, not eligible with no way forward) or unclear replies to an offer in
   one session. Say if you mean something else.
7. If ServiceNow or the holding table fails, the customer is told it was not done and offered a person; never "done".
8. Settings: allow the probe, `ask` before any live pytest run.
9. Commits: one per phase, only when you ask.
10. Until Marco confirms the SKU kinds, the mapping is ours and marked `UNCONFIRMED`; every SKU not in it goes to a person. Answered: the replay may run on it (D5).

## Open questions I cannot answer from the repo
- (Answered in Phase 1: price, tax, quantity and customer type exist; product kind does not - D1.)
- OQ-S3-1 (spec): who approves and how fast - the reply promises no time.
- OQ-S3-2 (Marco, in the spec): the official kind of each SKU; the mapping is `UNCONFIRMED` until he answers; the replay may use it (D5).
- OQ-S3-3 (Ravi): answered 2026-10-23, now D4 in the spec. No open question for Ravi remains.
