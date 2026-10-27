# ADR 0001: The middleware is the only code that reads orders from Ledgerline

- **Status:** accepted. In force since 2026-10-23 (`a4bc5de`, `f1f784c`).
- **Written:** 2026-10-27, at `62b8228`, for the engineer who will be asked "why can't I just query Ledgerline here?"
- **Sources:** the code at that commit and `git log`. Every fact carries the commit it first appears in. Nothing here is from
  memory. Where the record is silent, this says so.

## Context

- Ledgerline is DemoStore's ERP, an old Oracle system with no API and its own owner, the database administrator (discovery
  notes of 7 Oct, `ed0f356`; `docs/problem-statement.md`, `72b1e64`).
- The Director of E-commerce Engineering owns the systems around it. He named three fears: our code slowing the ERP in the
  middle of a sale, an account with more rights than it needs, and code nobody on his team understands. He asked for read-only
  access first, an exact list of what we read and write, and code review by his team (`ed0f356`). How the assistant reads
  Ledgerline was an open question: "the access path is not decided" (OQ-7, `72b1e64`).
- The requirements this serves (`docs/spec-2.md`, `a4bc5de`): B7, the status, the promised date and the parcels come from
  Ledgerline as its owner gives them to us; B10, a customer only ever sees her own orders and parcels.
- Ledgerline has no change time on any table, and `ORD_DT` does not move when a status does (`docs/live-shapes.md`,
  `06ac452`).

## Decision

Every read of orders from Ledgerline in the product goes through one module, `ledgerline.py` (the "middleware"): a read-only
account, a read-only transaction, and a fixed query for each question (IT9, `a4bc5de`; the code, `f1f784c`). Three things
besides the middleware touch Ledgerline, and are the named exceptions below.

## Options we looked at

The repository has no document that sets out alternatives for the middleware as a whole. What the record shows being weighed,
each decided on its own date:

| Question | The options in the record | What was chosen | Where |
|---|---|---|---|
| Do the chat tools read Ledgerline on every message? | The record states the rule (IT10) and does not list the alternative. | The tools read only our own order store, filled hourly through the middleware. | `docs/spec-2.md`, `a4bc5de` |
| How does the hourly load know what changed? | (a) read all orders each run, with an upsert; (b) compare a hash of each row with the store and write only the rows that differ. A "changed since" query was not possible. | (a), on 2026-10-23: "Ledgerline has no change time and stays untouched", and a full read is cheap at 33 orders. | `docs/live-shapes.md`, `docs/spec-2.md` decisions, both `06ac452` |
| Can Ledgerline get a change column? | Ask its owner, or add it ourselves. | We ask (OQ-S2-1); "we do not add it ourselves". Open. | `docs/spec-2.md`, `06ac452` |
| Where does the money of a return come from? | Read live from Ledgerline at prepare time, or put the order lines in the store (stale up to an hour, one more table). | Live, through the middleware. | `docs/plan-3.md`, `e218104`; the code, `ORDER_LINES` in `ledgerline.py`, `2934149` |
| Where does the product kind of an item come from? | A mapping of the SKU in code, or a guess from the free text of the item description. | The mapping (D1); an unknown SKU goes to a person. | `docs/spec-3.md`, `e218104`; `kinds.py`, `2934149` |

Not in the record, so not claimed here: a vendor or database-link route, replication, a view on Ledgerline's side, or an
export file. If the database administrator or the Director remembers any of them being considered, add the row here.

## Reason

The three fears map onto what the code does, each with the commit that put it there:

- **Slowing the ERP.** Every query runs in `SET TRANSACTION READ ONLY` and is rolled back and closed (`f1f784c`,
  `test_ledgerline.py::test_the_session_is_read_only_and_closed`). The chat never reads Ledgerline for an order's status: it reads
  the store, and the hourly job reads Ledgerline (IT10, IT11, `a4bc5de`; `pipeline.py`, `8ef23b8`). The one live read in a chat
  is the money of a return, one order at a time (`2934149`).
- **A reader with too many rights.** The account `LL_READER` is SELECT on five tables and nothing else (the sandbox copy of the
  grant, `c231832`; the account in the settings from `a4bc5de`). The queries use four of them, `LL_CUST`, `LL_ORD_HDR`,
  `LL_ORD_LN`, `LL_SHPMT`; `LL_INV_HDR` is granted and not queried anywhere in product code. The fast test
  `test_queries_only_read` fails on any query that is not a `SELECT` or that contains INSERT, UPDATE, DELETE, MERGE, DROP,
  TRUNCATE, ALTER or CREATE (`f1f784c`).
- **Code nobody understands.** All the SQL is on one page, `ledgerline.py` (217 lines at `62b8228`): the order number and the
  customer are bind parameters, never pasted into the text, and the owner check is in the query (`WHERE ... LOWER(c.EMAIL_ADDR) =
  :customer`), so a different customer's order comes back as "not found" (`f1f784c`; `test_another_customers_order_returns_nothing`).
  This is the list "exactly what we read" that was asked for.
- **A code outside our word list is an error, not a guess.** Ledgerline's letter codes become our words through `STATUS` and
  `CUSTOMER_TYPE`; an unknown code raises (`f1f784c`, `2934149`).

The only thing that writes to Ledgerline is not the middleware: `drafts.py` inserts one return draft into `LL_RTN_REQ_STG`
through the separate writer account, never updates one, and never sets a status (`df9d750`; the account in `config.py`,
`e218104`).

## Consequences

- **The exceptions, named.** None of them reads orders for the chat.
  1. `drafts.py` runs one `SELECT` on the staging table `LL_RTN_REQ_STG`, to read back a draft with the same key, through the
     writer account (`df9d750`). It is the one place besides the middleware that may open a connection.
  2. `probe_live.py` is a tool for people: table lists and sample rows with the read-only account, emails masked (`06ac452`).
  3. `checks.py` imports `ledgerline` only for the `STATUS` words, and opens no connection (`5866c0f`); that makes the chat
     process import `oracledb` (`docs/quick-fixes.md`, `e71bbde`).

  A fourth place turned up when the rule was made a test: `doctor.py`, another tool for people, opens a read-only connection and
  counts the rows of `LL_ORD_HDR` as a health check (`c231832`). It is named in the test as well.
- **The rule is a fast test.** `test_ledgerline_only.py` reads every Python file outside `sandbox/` and `builds/` and fails when
  a file other than `ledgerline.py` and `drafts.py` opens a connection with `oracledb` or `cx_Oracle` (a call, a bare
  `oracledb.connect` reference, an alias, a `from` import, or `import_module`). `probe_live.py` and `doctor.py` are listed in the
  test by name as tools for people, and the test fails if the chat, a job or another test imports them. It checks the
  source, not behaviour: a connection made by other means, such as a shell-out to `sqlplus`, is not seen. It was added in the
  commit that introduced this record (`git log -- test_ledgerline_only.py`).
- **Each hourly run reads every order and shipment** (`ALL_ORDERS`, `ALL_PARCELS`, `f1f784c`), and the full read is recorded as a
  quick fix: fine at 33 orders, a load on the ERP in the middle of a sale if the count grows (`docs/quick-fixes.md`, `06ac452`).
- **One unknown code stops the whole load.** `status_word` raises, `pipeline.main` exits non-zero and writes nothing
  (`pipeline.py`, `8ef23b8`; the runbook, entry 2).
- **The bulk query has no owner filter.** The per-order queries check the customer inside the SQL; the bulk read for the
  pipeline cannot, and the order store applies the owner check on read (`store.py`, `965d71a`).
- **A change in Ledgerline's tables breaks one module and its tests,** not the chat: the tools see our shape (`_build` in
  `ledgerline.py`, `f1f784c`).

## What would make us decide again

- **Ledgerline gets a change column** (OQ-S2-1, `06ac452`): the load becomes a "changed since" query, and the full read goes.
- **The order count grows, or the full read is felt on a sale day** (the quick-fix row, `06ac452`): move to that query, or to the
  hash comparison the record names as option (b).
- **Ledgerline gets an API** (it has none today, `ed0f356`): the middleware's job moves behind it and the SQL goes.
- **The owner changes the account's rights, or asks for a second kind of read.** The list of tables above is the review list.
- **A second module needs Ledgerline.** The test will fail. Put the query in `ledgerline.py` instead of adding the module to
  the test's list; add to the list only for another tool for people, and add the row here.
