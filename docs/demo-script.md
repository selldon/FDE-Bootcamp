# Pilot demo for the steering committee (5 minutes)

Who watches: Lena Brandt (sponsor), Marco Rossi (support), Ravi Menon (systems), Hannah Weber (business customers).
What they decide after it: whether the pilot goes live for a small share of visitors.

## Before the meeting

- Run it twice the day before, on the same data, with the same three stories. Note anything that varies.
- The widget, the ServiceNow approvals page and the live queue are open in three tabs. Nothing else.
- A recording of the full run is ready, in case the network or a system fails in the room.
- The numbers slide (shadow mode against the baseline) comes right after the demo, not inside it.

## Three stories, one per goal

1. **Where is my order (Lena: fewer waiting customers).** Maya asks about DS-20417. The assistant asks for the
   one-time code first, then gives the status and the date from the carrier. Say: the date comes from a tool, never
   from the model; with old carrier news it would not give a date at all.
2. **A return (Marco: the same answer for the same case, no money moves alone).** Ethan wants to return his headset
   from DS-20531. The assistant checks the window and the item, shows the amount and asks. He says yes. A refund
   draft appears as a task on the approvals page. Say: nothing is paid; a person approves.
3. **A person, at once (Marco: no angry customer stuck with a bot).** "Third time I am writing. I want a real
   person, now!" The chat goes to the live queue with a summary. Say: the hand-off is decided in code, not by the
   model's mood.

## What we do not show, and say so

- Contract prices for business customers (waits for the role check, Hannah).
- Product questions and attachments (not in the pilot).
- Customers in other languages (tested in English only).

## Likely questions

- Lena: "How much does a chat cost, and how many does it resolve?" - the numbers slide, from the same views.
- Marco: "What happens when it is wrong?" - the hand-off rules, the confident-wrong count, and the kill switch.
- Ravi: "What does it touch in Ledgerline?" - read-only, plus one staging table for return drafts.
- Hannah: "When do business customers get it?" - after the role check; not in the first launch.
