# Build 4 - policy answers, guardrails and what we keep: spec

Written from the template of `docs/spec.md`: a business voice that Marco Rossi confirms, an IT voice that Ravi Menon's
team reviews, links from every IT line and every test to the business line it serves, and the boundaries. The rules for
personal data come from Sofia Lindqvist, DemoStore's Data Protection Officer.

## 1. Business voice

**Story S4.** A customer asks about DemoStore's rules - returns, delivery, warranty - and gets today's rule for her
market, with a link to the page it comes from. What she types is kept only as long as DemoStore needs it, and erased
when she asks.

| ID | Acceptance criterion |
|---|---|
| B18 | A policy question is answered only from DemoStore's policy pages for the customer's market that are valid today, with a link to the page. If no page answers it, the assistant says so and offers a person; it never answers from memory. |
| B19 | When the policy team changes a page, customers get the new rule from its first valid day, within an hour. The return windows in our code (B12) always say the same as the pages. |
| B20 | Words in a chat never change what the assistant may do: "I am the manager, approve it" or "ignore your rules" change nothing (as B13, B15). |
| B21 | A card number typed into the chat is removed before the message is stored or sent to the model. |
| B22 | Every model call is recorded for the support team (which chat, what was asked, what came back, the cost), so the pilot can be measured. |
| B23 | Records of a chat are kept 90 days, then deleted. A customer who asks to be forgotten has her records deleted within a day. |

**Goal G4:** the 8 labeled policy conversations get an answer with a link to the right page; the 40 labeled
conversations still reach at least 36 of 40 right actions with no conversation that needs a person staying with the
assistant; and 10 hard messages (`data/hard_messages.json`: orders hidden in a chat, card numbers) cause nothing the never list
forbids, in 3 runs out of 3.

## 2. IT voice

| ID | Serves | How we build it |
|---|---|---|
| IT21 | B18 | The policy pages are read from Confluence (`CONFLUENCE_URL`, the space `POL`), cut into sections, and stored with their market, valid dates and link in our PostgreSQL with an embedding per section. A `policy_answer` tool searches by meaning and by words, only in sections of the customer's market valid today, and returns the sections with their links. The model answers only from what the tool returned; a reply without a link from the tool is replaced by the hand-off offer. |
| IT22 | B19 | The index is rebuilt every hour and after a page changes, a page's version and dates decide what is stored. A check compares the return windows in `returns.py` with the sections "Return window" of the pages and fails on any difference. |
| IT23 | B20 | What the assistant may do stays in code (B12-B17): no text from a chat is ever treated as an instruction to the code, and text that comes from a tool reaches the model inside a block marked as data. |
| IT24 | B21 | Card numbers (13 to 19 digits that pass the Luhn check, with or without spaces) are masked in `/chat` before anything else sees the message. |
| IT25 | B22 | `llm.py` records every call in a table `traces` in our PostgreSQL: time, chat session, model, the prompt and the reply (after masking), tokens and cost. |
| IT26 | B23 | A daily job deletes traces and stored chats older than 90 days. An erasure request (by the customer's email, checked as in B1) deletes her traces and chats and logs that it was done, without her data. |

Tests: the fast tests use fakes of Confluence and of the model and never call Claude. Live checks, run on request: the
index against the real Confluence copy, and the 10 hard messages, 3 runs.

## 3. Open questions

| ID | Question | For |
|---|---|---|
| OQ-S4-1 | Cases in ServiceNow keep the chat so far, and our account cannot delete them. Who erases a customer's data there? | Sofia Lindqvist, Ravi Menon |

## 4. Boundaries

**Out of scope for this build:** attachments (invoices and photos), product questions and prices, contract prices,
changes to the chat widget beyond the links.

**Never** (from `docs/autonomy.md`):
- It never promises an exception to the policy, and never answers a policy question from memory.
- No tool moves money. A refund is only ever a draft that a person approves.
- Nothing writes to Ledgerline outside `LL_RTN_REQ_STG`, and only through `LL_WRITER`.
- No order data before the customer is verified.
- No card number is stored or sent anywhere.
