# Brief: going live - 5 % of visitors, a control group, two weeks, then 25 %

Day 11. Shadow mode and the pilot page convinced Lena: the assistant goes live for one intent, "where is my order", for
5 % of the website's visitors. Everyone else is the control group: their chats go to a person in ServiceNow, as before,
at the same time. The rollback lines below were signed by Lena, Marco and the Finance and Returns Controller before
the launch. We cannot wait two real weeks in this course, so simulated customers give us the traffic; the page and the
report say so. In a real project these numbers come from live visitors.

## The signed rollback lines

- Confidently wrong: more than 1 in 100 in the day's sample -> roll back.
- Hand-off: fewer than 95 in 100 of the chats that need a person reach one -> roll back.
- Chats left without an answer, and the customer rating: worse than the control group by more than the margin -> roll back.
- When all lines hold for two weeks, we widen to 25 % and add returns (refunds stay drafts a person approves).

## What to build

1. **The launch switch**, a setting in our database: the share of visitors (5 %), the intents that are live, and on/off.
   A visitor's group is decided once, from their visitor id, and stays the same. Off sends every new chat to a person
   within seconds, with no deploy. The control group's chats go to the live queue in ServiceNow, as before the assistant.
   Both groups are written to the same table, so the page can compare them.
2. **Two simulated weeks.** Simulated customers write to the chat service: a visitor id, a day of the two weeks, a
   question and a few follow-ups, from customer profiles like the ones in the sandbox's simulator (day 8). Only the
   assistant's group calls Claude; the control group's outcomes come from how people answered the same kinds of chats
   in the old ServiceNow chats. The truth of each order is known to the simulation, so a wrong status given as fact is
   counted automatically (in real life: the day's sample a person checks). Keep it small: at most 150 conversations with
   the assistant in all.
3. **The comparison on the pilot page**: both groups side by side for each signed line (resolved, handed off, left
   without an answer, repeat contacts within 7 days, rating, cost per contact), each difference with its 95 % interval
   and the sample size, and whether the line holds.
4. **The drill.** On one simulated night the carrier's file does not arrive. The assistant must not give yesterday's
   status as today's. If it does, the day's numbers cross the confidently-wrong line: the page shows the alert, we switch
   the assistant off, find and fix the cause test first, replay the labeled conversations and the bad day's chats, and
   switch it on again. Write down how long the assistant was off.
5. **The decision and the report.** After the second simulated week, if the lines hold: 25 % and returns. A short
   `docs/week-2-report.md` from the same numbers: operator hours saved per week, and what 100 % would mean, with the
   assumptions said out loud.

## Limits

- Simulated traffic is labelled as simulated everywhere: on the page, in the report, in every row it creates.
- The switch never needs a deploy, and turning it off never loses a chat that is already open.
- No refund is ever paid by the assistant; returns at 25 % make drafts only.
- Every model call goes through `llm.py`; the numbers come from code and SQL.
- A change to stored rows gets a restore point first. Fast tests still pass: `python -m pytest -q -m "not live"`.
