# DemoStore - discovery notes (raw)

FDE notes, week 1. No customer names, addresses or order numbers copied.

## Mon 5 Oct 2026 - call with Lena Brandt (Chief Digital Officer, sponsor)

- Opening line: "We want a chatbot, like everyone else."
- Asked: "What should be different in three months?"
  - "Customers wait too long during sales, and support costs keep growing."
- Pressure comes from other stores. No measured problem yet.
- Fears: money spent on a tool nobody uses. A public mistake, like the bots that invented a refund rule.
- Wants short updates with numbers and clear choices, not tech detail.
- Not in the agents' session (they talk more openly without managers).

## Tue 6 Oct 2026 - session with Marco Rossi (Head of Customer Support) + 2 agents

Goal: how the team answers "where is my order" and "how do I return this" today.
90 min: 30 talk, 60 shadowing. Read before: return policies in Confluence, help pages, a few old chats.

Marco:
- "During sales, customers wait up to twenty minutes."
- "About four in ten chats are where is my order." His number - count from a ServiceNow sample ?
- "My team should stop answering where-is-my-order chats all day."
- Wants fewer repeat questions. Same answer for the same case. No new screen - the team works in ServiceNow.
- Fears a bot that makes angry customers angrier, and agents cleaning up after wrong answers.
- Better experience, in a number: "Fewer customers who ask the same thing twice."

Shadowing - Agent A, a where-is-my-order chat:
- In the interview: "about two minutes".
- Watched: chat arrives in ServiceNow -> copies the order number -> opens Ledgerline (ERP): shipped. Status there comes from last night's carrier file -> also checks the carrier's own website -> saved reply, changes the date by hand.
- Took about four minutes, not two.
- Agent A: "I never trust the carrier file in the morning."

Shadowing - Agent B, a return chat, customer in Germany:
- Does not search Confluence. Opens her own spreadsheet with the return window for each market.
- Not mentioned in the interview. Second copy of the rules. Same as Confluence? Compare ?
- Slower chat, about eight minutes: market, delivery date, policy.

Hard chats watched:
- Company customer asks for a contract price - agent passes it on.
- Angry customer: "Third time I am writing. I want a real person, now!"

Read 20 real chats with the agents:
- About half need order data from Ledgerline.
- Some come from company customers with their own contract terms.
- Some customers simply want a person.

Open:
- Refund threshold: above which amount must a person approve a refund? Asked Marco - he does not know the number. Set by the Finance and Returns Controller, not met yet. Nobody answered ?

Same day: summary sent to Marco for corrections.

## Wed 7 Oct 2026 - short notes

Ravi Menon (Director of E-commerce Engineering, owns the systems):
- Ledgerline is an old Oracle system, no API. Has its own owner, the database administrator.
- Fears: our code slowing the ERP in the middle of a sale. An account with more rights than it needs. Code nobody on his team understands.
- -> read-only access first. List exactly what we read and write. Code review by his team.
- Access requests can take weeks - start them this week.

Hannah Weber (Head of DemoStore Business Sales):
- Wants company customers served faster.
- Contract price only to a customer with the right to see it. Roles: a buyer places orders, a manager approves them.
- Prices come from Atlas, the store platform.
- Hard no: one company's private terms shown to another company.

Still to meet this week: Finance and Returns Controller, Sofia Lindqvist (Data Protection Officer).
