# Build 1 - the assistant prototype: spec

The document the coding agent builds from. Two voices: the business voice (who needs what, and why) is confirmed by
Marco Rossi, Head of Customer Support; the IT voice (how we build it) is reviewed by Ravi Menon's team. Every IT line
names the business line it serves, and every test names its line too. When a decision changes, this file changes first.

## 1. Business voice

**Story S1.** A customer asks where her order is.

| ID | Acceptance criterion |
|---|---|
| B1 | A customer who is not verified sees no order data. Verified means she typed the one-time code we sent to her email. |
| B2 | A verified customer who asks about her order gets its status and the promised date, as DemoStore's systems have them. |
| B3 | A customer who did not give an order number is asked for it. |
| B4 | A customer who asks for a person gets one. The person sees the chat so far. |
| B5 | A question this build does not cover goes to a person. The assistant does not try to answer it. |
| B6 | A customer only ever sees her own orders. |

**Goal G1** (from the prototype plan): at least 36 of the 40 labeled conversations get the right action, and no
conversation that needs a person stays with the assistant.

## 2. IT voice

| ID | Serves | How we build it |
|---|---|---|
| IT1 | B2, B6 | Two tools: `find_order` takes only the order number; `delivery_status` takes a tracking number. The customer ID comes from the verified session, never from the model. A customer could push the model to write someone else's ID. |
| IT2 | B1 | The order tools stay locked until the one-time code is checked: before that, they return no order data. |
| IT3 | B1 | One-time code: six digits, valid 10 minutes, 3 tries. In this build the email is a fake: the code is written to `data/outbox.jsonl` instead of being sent. |
| IT4 | B2 | Dates and statuses come only from the tools. In this build Ledgerline is a fake (`data/orders.json`) and so is the carrier's nightly file (`data/carrier.csv`), behind the same tools, so the real systems replace them later without changing the agent. |
| IT5 | B4, B5 | A `hand_off` tool opens a case in a fake ServiceNow (`data/cases.jsonl`) with a short summary and the chat so far. The reply tells the customer that a person will take over. |
| IT6 | B4 | After ten rounds, the loop stops and opens a case, as in IT5. |
| IT7 | all | Every model call goes through our adapter (`llm.py`); the model name lives in one constant. |
| IT8 | G1 | `replay.py` runs the 40 labeled conversations (`data/conversations.json`) through the agent, each as a verified session of the order's owner, and prints the action taken, the score, and every conversation that needed a person but stayed with the assistant. For this build, the labels of later intents (`answer_policy`, `answer_product`, `start_return`, `check_buyer_role`) count as `hand_off`. The replay calls Claude, so it is not part of the pre-commit hook. |

Tests: the fast tests use the fakes and never call Claude; they run in the pre-commit hook. Tests that call Claude are
marked `live` and run on demand. Example: B1 -> IT2 -> `test_unverified_chat_gets_no_order_data` - a chat with no code
asks about a real order and gets nothing back.

## 3. Boundaries

**Out of scope for this build:** the real Ledgerline connection, returns, contract prices, policy answers, real email,
real ServiceNow.

**Never** (from `docs/autonomy.md`):
- No tool moves money.
- Nothing writes to Ledgerline outside the holding tables the ERP owner agreed to.
- No order data appears before the customer is verified.
- Dates come only from a tool, never from the model.
