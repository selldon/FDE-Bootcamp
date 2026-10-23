# DemoStore - problem statement

Source: `docs/discovery-notes.md`, week 1 (5-7 Oct 2026). Brackets give the line of the notes, for example [L21]. Figures marked *claimed* come from interviews and are not yet measured.

## Who has the problem

- **Customers** wait for an answer in support chat, most of all during sales [L9, L21].
- **Support agents** (team of Marco Rossi, Head of Customer Support) answer "where is my order" chats all day and want fewer repeat questions [L23, L24]. They work in ServiceNow [L24].
- **Company customers** (Hannah Weber, Head of DemoStore Business Sales) need to be served faster [L62]. Some chats come from company customers with their own contract terms [L45].
- **Sponsor**: Lena Brandt, Chief Digital Officer. Her answer to what should be different in three months: customers wait less and support costs stop growing [L8-L9].

## What it costs today

- **Wait time.** Claimed: during sales, customers wait up to twenty minutes [L21].
- **Volume.** Claimed: about four in ten chats are "where is my order" (Marco's number, not yet counted from a ServiceNow sample) [L22]. In 20 real chats read with the agents, about half needed order data from Ledgerline [L43-L44].
- **Agent time per chat** (shadowing, one chat each):
  - Where is my order: about four minutes; the agent said two [L29, L31]. The agent copies the order number from ServiceNow, checks Ledgerline (ERP), then also checks the carrier's website, because the ERP status comes from last night's carrier file. Then the agent sends a saved reply and changes the date by hand [L30]. The agent: "I never trust the carrier file in the morning" [L32].
  - Return, customer in Germany: about eight minutes [L34, L37]. The agent uses her own spreadsheet with the return window for each market instead of Confluence [L35].
- **Inconsistency.** The return rules exist in at least two places: Confluence and an agent's spreadsheet [L18, L35-L36]. Whether they match is not known [L36]. Marco wants the same answer for the same case [L24].
- **Cost of support.** Lena says support costs keep growing [L9]. There is no measured problem yet; the pressure comes from other stores [L10].

## What success looks like

In the stakeholders' words:

- Customers wait less during sales [L9].
- Support costs stop growing [L9].
- Agents stop answering "where is my order" chats all day [L23].
- Fewer customers ask the same thing twice (Marco's number for a better experience) [L26]; fewer repeat questions [L24].
- The same case gets the same answer [L24].
- Company customers are served faster [L62]; one company's private terms are never shown to another company [L65].
- No money spent on a tool nobody uses, and no public mistake such as a bot that invented a refund rule [L11].
- No bot that makes angry customers angrier, and no agents cleaning up after wrong answers [L25].

The notes give no numeric targets or baselines; see `requirements.md`, open questions.

## Constraints stated so far

- Agents keep working in ServiceNow; no new screen [L24].
- Ledgerline is an old Oracle system with no API and its own owner, the database administrator [L56]. Ravi Menon (Director of E-commerce Engineering) wants read-only access first, an exact list of what we read and write, and code review by his team [L58].
- Ravi fears our code slowing the ERP in the middle of a sale, an account with more rights than needed, and code nobody on his team understands [L57].
- Contract prices come from Atlas, the store platform, and are shown only to a customer with the right to see them [L63-L64].
