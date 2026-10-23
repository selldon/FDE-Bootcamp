# Build 2 - the middleware tools, the carrier pipeline and the order store: spec

Written from the template of `docs/spec.md`: a business voice that Marco Rossi confirms, an IT voice that Ravi Menon's
team reviews, links from every IT line and every test to the business line it serves, and the boundaries.

## 1. Business voice

**Story S2.** A customer asks where her order is, and gets the answer from DemoStore's real systems, not from a test file.

| ID | Acceptance criterion |
|---|---|
| B7 | The status, the promised date and the parcels come from Ledgerline, the ERP, as its owner gives them to us. |
| B8 | The carrier's last news about a parcel comes from its nightly file, so the customer hears where the parcel is. |
| B9 | When the carrier's last news is more than 30 hours old, the assistant gives no delivery date and offers a person. |
| B10 | A customer only ever sees her own orders and parcels (as B6). |
| B11 | Ravi's team can run the data loads again after a failure, and nothing breaks or doubles. |

**Goal G2:** the 40 labeled conversations still reach at least 36 of 40 right actions, now on the copy of Ledgerline,
and no conversation that needs a person stays with the assistant.

## 2. IT voice

| ID | Serves | How we build it |
|---|---|---|
| IT9 | B7, B10 | The middleware is the only code that reads Ledgerline: one fixed query per question, the read-only account from `.env`, the order number and the customer as bind parameters, the owner check inside the query. Ledgerline's letter codes become our words through one mapping table (N new, S part shipped, F shipped, D delivered, X cancelled). |
| IT10 | B7, B8 | The order store is a few tables in our own PostgreSQL (`STORE_URL`): orders and parcels in our shape. The chat tools `find_order` and `delivery_status` read only the order store, never Ledgerline or the carrier directly. |
| IT11 | B7, B8, B11 | An hourly pipeline fills the order store: orders and shipments through the middleware, and the newest carrier file from the SFTP server. Ledgerline has no change time on any table, so each run reads all orders and shipments (33 orders in the copy); IT12 makes that safe. The store keeps the time of the last successful run; it moves forward only after a run has passed its checks. When Ledgerline gets a change column (OQ-S2-1), the run reads only the rows that changed since that time. |
| IT12 | B11 | Every write to the order store is an upsert by key (order number, tracking number), so running the same load twice leaves the store the same. |
| IT13 | B7, B8 | Four checks on every load, as tests in code: the number of rows is close to a normal run, every parcel belongs to an order we know, every status is one of ours, the newest carrier news is recent enough. A failed check stops the load; the store keeps the last good data. |
| IT14 | B9 | The age of the carrier's news is decided in code: older than 30 hours means no date, and the reply offers a person. The carrier gives a date without a time, so the age counts from the end of the news date (midnight at the end of that day, in UTC): news dated the 22nd is 0 hours old at the end of the 22nd and turns 30 hours old at 06:00 on the 24th. The same age rule serves the fourth check of IT13. |

Tests: the fast tests use fakes of Ledgerline and the SFTP server and never touch the real systems. One live check, run
on request, reads the real copy and the real SFTP server.

## 3. Open questions

| ID | Question | For |
|---|---|---|
| OQ-S2-1 | Can Ledgerline's order tables (`LL_ORD_HDR`, `LL_SHPMT`) get a change column (the time of the last change to the row), so the pipeline can read only what changed? Today none has one, and `ORD_DT` does not move when the status does. We ask for it; we do not add it ourselves, and until it exists every run reads all orders. | Ravi Menon, the database administrator |
| OQ-S2-2 | The carrier's file gives a date with no time. Does the carrier publish the time the file was produced, so the age of its news can be more exact? Until then IT14 counts from the end of the news date. | Marco Rossi, Ravi Menon |

## 4. Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-23 | Each run reads all orders and shipments; no "changed since" query (IT11). | Ledgerline has no change time and stays untouched. At pilot scale (33 orders) a full read is cheap, and every write is an upsert (IT12). Noted in `docs/quick-fixes.md`. |
| 2026-10-23 | The age of the carrier's news counts from the end of its news date (IT14). | The file has a date but no time. The end of the day is the latest the news can be from, so the rule never says "fresh" for news that is older than it looks. |

## 5. Boundaries

**Out of scope for this build:** returns and refunds, contract prices, policy answers, real email, real ServiceNow,
changes to the chat widget.

**Never** (from `docs/autonomy.md`, and Ravi's conditions for the read-only access):
- Nothing writes to Ledgerline. We have a read-only account, and no other is asked for in this build.
- No tool moves money.
- No order data appears before the customer is verified.
- Dates come only from a tool, never from the model.
