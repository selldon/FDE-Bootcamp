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
| IT11 | B7, B8, B11 | An hourly pipeline fills the order store: orders and shipments through the middleware, and the newest carrier file from the SFTP server. It loads only what changed since the last successful run; the time it keeps moves forward only after a run has passed its checks. |
| IT12 | B11 | Every write to the order store is an upsert by key (order number, tracking number), so running the same load twice leaves the store the same. |
| IT13 | B7, B8 | Four checks on every load, as tests in code: the number of rows is close to a normal run, every parcel belongs to an order we know, every status is one of ours, the newest carrier news is recent enough. A failed check stops the load; the store keeps the last good data. |
| IT14 | B9 | The age of the carrier's news is decided in code: older than 30 hours means no date, and the reply offers a person. |

Tests: the fast tests use fakes of Ledgerline and the SFTP server and never touch the real systems. One live check, run
on request, reads the real copy and the real SFTP server.

## 3. Boundaries

**Out of scope for this build:** returns and refunds, contract prices, policy answers, real email, real ServiceNow,
changes to the chat widget.

**Never** (from `docs/autonomy.md`, and Ravi's conditions for the read-only access):
- Nothing writes to Ledgerline. We have a read-only account, and no other is asked for in this build.
- No tool moves money.
- No order data appears before the customer is verified.
- Dates come only from a tool, never from the model.
