# DemoStore assistant - autonomy

How far the assistant may go in the pilot. Each level is kept in code, not only in the prompt.
These are the most it may ever do; more freedom needs the numbers and a written yes.

## Levels

| Level | What the assistant does |
|---|---|
| Answers | Reads data and tells the customer; changes nothing. Where an order is and when it should arrive. The return policy for the customer's market, with a link to its Confluence page. Whether an item can be returned: code decides from the rules, the model explains the result. |
| Does | Small, safe actions that are easy to fix: sends a one-time code by email to check who the customer is; hands the chat to a person (a ServiceNow case with a summary). |
| Drafts | Prepares, a person finishes: after a clear yes from the customer, a refund draft in a Ledgerline holding table and an approval task in ServiceNow. A person approves every refund, whatever the amount. |
| Never | See the never list. |

## Never list

- No tool moves money.
- It never changes an order or a price.
- Nothing writes to Ledgerline outside the holding tables the ERP owner agreed to.
- It never promises an exception to the policy.
- No order data before the customer is verified (the one-time code is checked).
- Dates come only from a tool, never from the model.

## Assumptions

| Assumption | How we check | Owner | By |
|---|---|---|---|
| The carrier's nightly file is fresh enough for "where is my order". | Compare 50 morning answers with the carrier's website. | Marco Rossi | 16 Oct |
| The policies in Confluence match what agents really use. | Compare Confluence with the agents' spreadsheets. | Marco Rossi | 16 Oct |
| Customers accept a code by email before they see their order. | Drop-off at the code step in the pilot. | Lena Brandt | pilot week 2 |

## Risks

| Risk | Who worries | Control |
|---|---|---|
| A wrong refund | Finance and Returns Controller | Draft + approval by a person |
| Personal data shown to the wrong person | Sofia Lindqvist, Data Protection Officer | Identity check in code |
| A wrong delivery date said with confidence | Marco Rossi | A person checks a sample of chats |
| A customer cannot reach a person | Customers | A way to a person is always open |

## Not in the pilot

Contract prices for company customers (need a check of the buyer's role), warranty repairs, draft replies for agents
to send from ServiceNow.

Signed: Lena Brandt (sponsor), Ravi Menon (systems), Marco Rossi (support).
