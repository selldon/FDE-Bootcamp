# Brief: the pilot dashboard - shadow mode against the baseline

Day 10. Shadow mode answers every new live chat, and nobody sees the answers. Lena Brandt, our sponsor, and Marco Rossi,
the Head of Customer Support, now ask the question the pilot exists for: would the assistant have helped, and what would
it cost? They will not read a database. They need a page they can open any day, with the same numbers every time, and a
way for Marco's team to say which answers were right.

## What to build

1. **The numbers in one place** (`pilot.py`): one function that reads `shadow_chats` and returns every number the page
   shows, so a number means the same thing every week:
   - chats per day and per market, and what the assistant would have done (its action);
   - by intent: the chat service already decides the intent of each message; the worker stores it the same way, so the
     numbers can say how many "where is my order" chats the assistant would have answered without a person;
   - what a person checked (point 2): right, wrong, and **confidently wrong** (a wrong answer given as fact, the kind that
     hurts most), each with the size of the checked sample next to it;
   - the cost: tokens of every shadow answer, priced with the prices in `llm.py`; the cost of one chat, and of one chat
     the assistant would have resolved;
   - the baseline from discovery: one contact with a person costs about $7 and takes about 4 minutes; a ready-made product
     charges 99 cents per resolution. The success criterion from discovery: at least half of the "where is my order" chats
     solved without a person.
2. **A check by a person**: a short list of shadow chats, picked at random, with the customer's message, the assistant's
   answer and the agent's reply side by side. Marco's team marks each one: same as the agent, better, worse, or wrong
   (and, if wrong, whether it sounded sure). The marks are stored in our database with who marked and when.
3. **The page**: a second page of our widget app, for the team, at its own address. It shows the numbers of point 1 as
   plain tables, the checked sample with its marks, and the side-by-side list. It only reads, except for the marks.
4. **The words for Lena**: under the numbers, three plain sentences the page builds from them (where we are against the
   criterion, what it costs against a person, how sure we are given the sample size). No model writes them.

## Limits

- "Would have resolved" is an estimate: in shadow mode no customer reacted to the answer. The page says so, and every
  rate shows its base (how many chats, how many checked).
- A rate never hides a chat: every share of a whole is divided by the same total.
- Customer messages stay inside DemoStore: the page is for the team on the internal network only (no public address before
  day 11), and the masking we already do (card numbers) applies. Shadow rows follow the same 90-day retention as traces.
- Every model call still goes through `llm.py`; the intent check is the one the chat service uses, not a new prompt.
- The numbers come from code and SQL, never from a model.
- Fast tests still pass: `python -m pytest -q -m "not live"`.
