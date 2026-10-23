# Build 3 - verified actions: returns, refund drafts, approvals and the hand-off case: spec

Written from the template of `docs/spec.md`: a business voice that Marco Rossi confirms, an IT voice that Ravi Menon's
team reviews, links from every IT line and every test to the business line it serves, and the boundaries. The levels
of autonomy come from `docs/autonomy.md`.

## 1. Business voice

**Story S3.** A customer wants to return an item. She learns at once whether she can, and why. If she can and she
says yes, a refund is prepared, and a person at DemoStore approves it. A customer who needs a person gets one.

| ID | Acceptance criterion |
|---|---|
| B12 | Whether an item can be returned is decided by DemoStore's rules for the customer's market, the same every time. The assistant explains the decision; it never makes one up. |
| B13 | Nothing is prepared until the customer has seen what will be refunded, for which item and how much, and has clearly said yes. |
| B14 | The refund for an item is its price and its share of the tax, to the cent; the refunds of all items of an order add up to what the customer paid. |
| B15 | Every refund is a draft that a person approves in ServiceNow, whatever the amount. The customer hears that it is waiting for approval, not that it is done. |
| B16 | A customer who presses "yes" twice, or whose message is sent again after a timeout, gets one draft, not two. |
| B17 | A customer who asks for a person, who is angry, or who is still stuck after two tries gets a person: a case in ServiceNow with a short summary the agent can trust, and the chat so far. |

**Goal G3:** the 30 borderline return cases (`data/borderline_returns.json`) get the right decision in every run;
the 4 labeled return conversations start a return; the 40 labeled conversations still reach at least 36 of 40 right
actions, and no conversation that needs a person stays with the assistant.

## 2. IT voice

| ID | Serves | How we build it |
|---|---|---|
| IT15 | B12 | The return rule is a function in code: 14 days from delivery in the UK and the EU, 30 days in the US (15 if the item was opened); opened earbuds and software never; a DemoStore Business customer always goes to a person. The decision comes from the function; the model only puts it into words. The market, the customer type and the delivery date come from DemoStore's systems, never from the customer or the model; whether the item was opened is asked from the customer. |
| IT16 | B13 | A `prepare_return` tool shows the customer the item and the amount and asks for a yes. Only a second step, after an explicit yes in the customer's own message, may create the draft. The yes is checked in code, not left to the model. |
| IT17 | B14 | The item's price and tax come from Ledgerline's order lines, through the middleware. Money is `Decimal`, never `float`. The tax of a line is split by item; the cent that is left over goes to the first item, so the parts always add up. |
| IT18 | B15 | The draft goes into Ledgerline's holding table `LL_RTN_REQ_STG` through the writer account `LL_WRITER`, the one write Ledgerline's owner agreed to. Then an approval task is created in ServiceNow (`sc_task`). The reply says the refund is waiting for approval. |
| IT19 | B16 | Each draft carries an idempotency key made from the session, the order and the line. The holding table keeps one draft per key, so a retry returns the same draft and creates no second task. |
| IT20 | B17 | The hand-off opens a case in ServiceNow (`interaction`) instead of `data/cases.jsonl`. The summary is written from the chat by the model and checked in code: it names the order number and the reason, and nothing the customer did not say. The triggers are decided in code: a request for a person, anger, two failed tries. |

Tests: the fast tests use fakes of Ledgerline, the holding table and ServiceNow and never call Claude. The 30
borderline cases are a fast test of the rule. One live check, run on request, writes one draft with a test key into
the real holding table and creates one real task, then reads them back.

## 3. Open questions

| ID | Question | For |
|---|---|---|
| OQ-S3-1 | Who approves refunds in ServiceNow, and how fast? Until we know, the reply promises no time. | Marco Rossi |

## 4. Boundaries

**Out of scope for this build:** exchanges, warranty repairs, contract prices, policy answers, real email, changes to
the chat widget beyond the new replies.

**Never** (from `docs/autonomy.md`):
- No tool moves money. A refund is only ever a draft that a person approves.
- Nothing writes to Ledgerline outside `LL_RTN_REQ_STG`, and only through `LL_WRITER`.
- It never changes an order or a price, and never promises an exception to the policy.
- No order data before the customer is verified.
- Dates come only from a tool, never from the model.
