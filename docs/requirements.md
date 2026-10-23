# DemoStore - requirements

Source: `docs/discovery-notes.md`, week 1 (5-7 Oct 2026). Every requirement and number carries the line of the notes it comes from, for example [L24]. A statement with no line in the notes is not a requirement; it is under **Open questions**. These are draft requirements, not yet confirmed by the stakeholders.

## User stories

### US-1. Order status ("where is my order")
As a customer, I want to learn where my order is, so that agents stop answering these chats all day [L23].

Acceptance criteria:
- The answer uses order data from Ledgerline (ERP) [L44, L30].
- The same case gets the same answer [L24].

### US-2. Returns ("how do I return this")
As a customer, I want to know whether and how I can return an item [L17].

Acceptance criteria:
- The answer takes the market and the delivery date into account [L37].
- The assistant never states an invented refund rule [L10].
- A refund above a threshold needs approval by a person [L49]. The amount is unknown (OQ-1).
- The same case gets the same answer [L24].

### US-3. Hand-off to a person
As a customer, I want a person when I ask for one [L46, L41].

Acceptance criteria:
- A customer who asks for a person (example: "Third time I am writing. I want a real person, now!") reaches an agent [L41, L46].
- The bot does not make angry customers angrier [L25].

### US-4. Support agent workflow
As a support agent, I want fewer repeat questions [L24], so that I stop answering "where is my order" chats all day [L23].

Acceptance criteria:
- Agents work in ServiceNow; there is no new screen [L24].
- Agents do not clean up after wrong answers [L25].
- Fewer customers ask the same thing twice [L26].

### US-5. Company customers
As a company customer, I want to be served faster [L62].

Acceptance criteria:
- A contract price is given only to a customer with the right to see it [L63].
- A buyer places orders; a manager approves them [L63].
- Prices come from Atlas, the store platform [L64].
- One company's private terms are never shown to another company (hard no) [L65].

### US-6. Sponsor reporting
As the sponsor, I want short updates with numbers and clear choices, not tech detail [L11].

Acceptance criteria:
- Updates are short and contain numbers [L11].
- Updates present clear choices [L11].

## Non-functional requirements

- **Correctness.** No invented refund rules [L10].
- **Consistency.** The same answer for the same case [L24].
- **ERP safety.** Read-only access to Ledgerline first [L58]; the exact list of what we read and write is documented [L58]; our code must not slow the ERP in the middle of a sale [L57].
- **Least privilege.** No account with more rights than needed [L57].
- **Maintainability.** Code is reviewed by Ravi Menon's team [L58] and understood by them [L57].
- **Data separation.** One company's private terms are never visible to another company [L65].
- **Fit with current tools.** Works with ServiceNow [L24], Ledgerline [L56], and Atlas [L64].
- **Lead time.** Access requests can take weeks; start them this week (week of 5 Oct) [L59].

## Open questions

Statements and numbers the notes do not support, plus things the notes say are unanswered. Owners are suggestions.

| # | Question | Source / why open | Suggested owner |
|---|----------|-------------------|-----------------|
| OQ-1 | Above which amount must a person approve a refund? | Marco does not know; set by the Finance and Returns Controller, not met yet; nobody answered [L49, L67] | Finance and Returns Controller |
| OQ-2 | What are the baselines and targets (wait time, share of "where is my order" chats, repeat-question rate, support cost, agent clean-up)? | No measured problem yet [L9]; the notes give no targets | Marco Rossi, Lena Brandt |
| OQ-3 | Is "about four in ten chats" correct? Can it be counted from a ServiceNow sample? | Marco's number, marked as unverified [L22] | Marco Rossi |
| OQ-4 | Is the twenty-minute wait during sales measured? | Quote only [L21] | Marco Rossi |
| OQ-5 | How fresh must order status be? Ledgerline status comes from last night's carrier file and agents also check the carrier's website; can the assistant get fresher data, or must it say the status may be stale? | Notes describe the workaround only [L30-L32]; no requirement stated | Ravi Menon, database administrator |
| OQ-6 | Which return rules are correct: Confluence or the agent's spreadsheet? Do they match? Are there other private copies? | "Same as Confluence? Compare ?" [L35-L36] | Marco Rossi |
| OQ-7 | How does the assistant read from Ledgerline, which has no API? What read-only access will its owner allow? | No API [L56]; read-only first [L58]; the access path is not decided | Ravi Menon, database administrator |
| OQ-8 | Who is the assistant's user: customers directly, agents inside ServiceNow, or both? Which channel, hours, languages and markets? | Lena asked for "a chatbot" [L6]; Marco says agents work in ServiceNow [L24]; a German-market return was seen [L34]; channel and markets not stated | Lena Brandt, Marco Rossi |
| OQ-9 | What should happen when the order cannot be found or the assistant is not sure? | No line in the notes (moved from requirements) | Marco Rossi |
| OQ-10 | When handing off to a person: what does the agent receive (conversation so far, order data), and does the bot ask anything first? | No line in the notes (moved from requirements); repeat questions are a pain [L24, L26] | Marco Rossi |
| OQ-11 | Which cases always go to a person: contract-price requests (agents pass them on today [L40]), refunds above the threshold [L49], angry customers [L41]? What should the assistant do with a contract-price request it cannot answer reliably? | Today's handling is seen; the target handling is not stated | Marco Rossi, Hannah Weber |
| OQ-12 | How are company customers identified and their roles (buyer, manager) checked? Where do contract terms live besides Atlas prices? | Roles [L63]; prices from Atlas [L64]; how roles are checked is not stated | Hannah Weber, Ravi Menon |
| OQ-13 | What data may be stored and for how long? What does the Data Protection Officer require? | Not met yet [L67]; no requirements recorded | Sofia Lindqvist |
| OQ-14 | How do we find out whether wrong answers happened and how many (how to measure "agents cleaning up")? | Fear stated [L25]; no measure stated | Marco Rossi |
| OQ-15 | What is the deadline (three months?), the budget, and how is "a tool nobody uses" measured? | Three-month horizon appears in a question [L7]; no deadline, budget or adoption target; fear at [L10] | Lena Brandt |
| OQ-16 | Are the one-chat timings (about four and eight minutes) typical? | Single observations [L31, L37] | Marco Rossi |
| OQ-17 | Did Marco correct the summary sent on 6 Oct? | Summary sent [L51]; no reply recorded | Marco Rossi |
| OQ-18 | Who approves the exact list of what we read and write, and how is the code review run? | Ravi asked for both [L58]; the process is not defined | Ravi Menon |
