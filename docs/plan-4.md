# Build 4 - plan

Builds `docs/spec-4.md` (B18-B23, IT21-IT26, goal G4) in small phases. Each phase ends in a check we can run: the fast
tests (`python -m pytest -q -m "not live"`, also run by pre-commit with ruff, mypy, tsc), a read-only look at Confluence and
PostgreSQL (`python probe_live.py build4`), a live check against Confluence or PostgreSQL, the 8 policy conversations, or the
10 hard messages (3 runs). Tick the boxes as each task is done. One phase at a time; stop after each one.

## Where we start

Done in Builds 1-3: `llm.py` (`ask`, `chat`, the only place that calls the model), `intent.py` (`policy_question` is already an
intent), `agent.py`, `app.py` (`/chat`, `/verify/*`, in-memory `SESSIONS`), `store.py` (our PostgreSQL, upserts, `FakeStore`),
`handoff.py`, `refunds.py`, `returns.py` (`WINDOWS`, `US_OPENED`), `replay.py`, 629 fast tests. `.env.example` already names
`CONFLUENCE_URL`; `config.py` does not read it yet.

Gaps found while reading the code (each is closed by a phase below):
- No policy answer: `app.py` sends `policy_question` to a person (`COVERED`), the system prompt says "policies - call hand_off", and
  `replay.py` scores the 8 `answer_policy` conversations as `hand_off` (`LATER`). C14 is labeled `answer_policy` but its intent is
  `return_request` (it asks about the opened-item rule).
- Nothing records model calls, nothing masks card numbers, nothing is deleted after 90 days. `llm.ask` / `llm.chat` take no session.
- The market is known only from a verified customer's order (Ledgerline `MKT_CD`). A policy question can come before the code.
- `data/conversations.json` labels the action, not the page, so G4's "link to the right page" has no answer key yet.
- Chats live only in memory (`SESSIONS`); the stored records are the new `traces`. ServiceNow cases cannot be deleted by us (OQ-S4-1).
- `requirements.txt` has no embedding library; `bge-small-en-v1.5` is English-only (DE/FR/IT pages or questions are a risk, Phase 1 looks).

Decisions made with the author (2026-10-26), to be written into `docs/spec-4.md` section 3 first (as D1-D4 of Build 4):
1. **Embeddings:** local, `fastembed` with `BAAI/bge-small-en-v1.5`. No text leaves the machine, no new key. The fast tests use a fake embedder.
2. **Answer key:** Phase 1 lists the pages of `POL`; Claude proposes the right page for each of the 8 policy conversations in
   `data/policy_key.json` (or "no page: offer a person"); the author confirms before any score uses it.
3. **Stored chats = traces + memory sessions.** No chats table. Erasure also drops her in-memory sessions. ServiceNow stays a known gap (OQ-S4-1).
4. **Market:** `/chat` takes an optional `market`; a verified customer's Ledgerline `MKT_CD` overrides it; no market known -> the
   assistant asks which country, never guesses. The widget is not changed (out of scope); the API and the replay send the market.
5. **Finding the traces of a customer:** `traces.customer_hash` = **HMAC-SHA256 of the lower-cased email with a secret from the settings**
   (`TRACE_HMAC_KEY`, named in `.env.example`; the author adds the value). Filled when the session is verified (earlier rows of that session
   are filled then). Erasure also matches her session ids.

Rules for the whole build:
- Fast tests use fakes of Confluence, the embedder, the model, the trace table and PostgreSQL where possible, and never call Claude.
  Live checks are marked `live`, run on request (the `ask` rule in `.claude/settings.json` prompts first).
- Confluence is read only (GET). Never started, stopped or changed; no page is edited to test B19 (that is tested with the fake).
- Containers are never started, stopped or changed. Our PostgreSQL gets new tables only (`policy_sections`, `traces`, `erasures`),
  created like `Store.create_tables`; live tests use temp tables/their own names, as `test_store_live.py` does.
- Every model call goes through `llm.py`; the model name stays one constant.
- Dates come from a tool or the injectable clock, never from the model. "Valid today" uses the same clock as `tools.clock`.
- `.env` is read by the code through `python-dotenv`, never opened by the agent. No secrets, emails or card numbers in docs, tests or commits
  (tests use the standard test card numbers from `data/hard_messages.json`).
- `data/held_out.json` stays closed. `data/conversations.json` is the only set we tune on.
- Checkpoint (global rule): the build adds files and tables. Two things delete rows: the index rebuild (stale sections) and the retention/erasure job
  (traces). Before the **first run of either against the real PostgreSQL**, dump the table with `pg_dump -t` to a file outside git and say so.
  Fast tests and live tests on temp tables need no restore point.
- Commits: one per phase, only when you ask.

## Phase 1 - settings and a read-only look at Confluence and PostgreSQL (groundwork for IT21-IT26)
- [x] Save this plan as `docs/plan-4.md`.
- [x] `docs/spec-4.md` section 3 "Decisions of 2026-10-26": D1-D4 above (embeddings, answer key, stored chats, market, HMAC) - the spec changes first.
- [x] `config.py`: `confluence()` (`CONFLUENCE_URL`; no login needed, so no user or password setting) and `trace_key()` (`TRACE_HMAC_KEY`);
      a missing name is an error that names it. `.env.example`: add `TRACE_HMAC_KEY=` with a comment (the author adds the value).
- [x] Fast tests of both settings (present; missing named) with `monkeypatch`; no network.
- [x] `probe_live.py build4` (read-only; existing output unchanged). Confluence - GET only: reachable, who we are, the pages of space `POL` (id, title, version,
      market and valid-date labels/properties wherever they are kept, language, body length; **no page bodies printed**). PostgreSQL - read-only:
      whether the `vector` extension is available/installed (`pg_available_extensions`), the existing tables, the server version. No POST/PUT/DELETE, no DDL.
- [x] Fast test that `probe_live.py` has no write verb or DDL (extend the Build 3 grep-style test).
- [x] `docs/live-shapes.md`, new section "Build 4": how Confluence exposes pages, versions, market and valid dates; the page language(s); how a section is found
      (headings); whether `vector` exists. Mark every difference from what Phases 5-9 assume and adjust those phases (note the change in the phase).
- [x] `data/policy_key.json`: Claude's **proposal** of the right page id (or "no page") for C07, C12, C14, C29, C30, C31, C32, C40, each with a one-line reason.
      Marked `UNCONFIRMED` until the author reads it.
- [x] `requirements.txt`: add `fastembed` (the install is the author's, because `pip install` is on the `ask` list).
- [x] **Stop and ask** if: the pages are not English (bge-small-en is English-only), `vector` is missing (fallback: embeddings as `real[]`, cosine in Python), valid
      dates/market are not in the pages in a usable way, or the space needs a login we do not have.
- [x] Check: fast tests, ruff, mypy green; `python probe_live.py build4` prints the shapes; the probe wrote nothing.
      Result 2026-10-26: 635 fast tests, ruff, mypy green; `python probe_live.py build4` read Confluence (GET) and PostgreSQL (read-only) and wrote nothing.
      `fastembed` is in `requirements.txt`; the author says it is already installed.

Found in Phase 1 (`docs/live-shapes.md`, "Build 4"). No stop-and-ask condition was met: the pages are English, no login, market and valid dates are in `metadata`.
Answered 2026-10-26:
1. `vector` 0.8.0 is available in PostgreSQL but **not installed**; `CREATE EXTENSION vector` changes the container's database. Needed in Phase 6. Answered: yes, create it in our own PostgreSQL (done in Phase 6, not before).
2. `data/policy_key.json` is a proposal: 5 of the 8 conversations have no page (C12 return shipping, C29 Canada, C31 holiday rule, C32 PayPal, C40 buy-back; C12 is the
   judgment call - page 1004 "Refunds" does not say who pays the shipping back). Confirmed by the author, C12 stays no page (`status` is `CONFIRMED` in the file).
3. `TRACE_HMAC_KEY` is in `.env` now (Phase 4 uses it).

## Phase 2 - card numbers are masked first (B21, IT24)
- [x] `masking.py`: pure `mask_cards(text)` - 13 to 19 digits, spaces or dashes between, Luhn-valid -> `[card number removed]`; keeps the rest of the message.
- [x] `app.py` `/chat`: the message is masked before anything else sees it (classify, history, offer check, hand-off summary, model).
- [x] Fast tests: the four card messages X07-X10 (spaced, plain, dashed, 15-digit Amex); a Luhn-invalid long number and an order number `DS-20377` are kept;
      two cards in one message; digits split by text are not joined; the history and the case carry only the masked text; `classify` and `answer` never get the digits
      (assert on the fake model's inputs); the module does no I/O.
- [x] Check: fast tests green. Result 2026-10-26: 648 fast tests, ruff, mypy green (tsc untouched).

## Phase 3 - every model call is recorded (B22, IT25)
- [x] `traces.py`: table `traces` (time, chat session, `customer_hash` null, model, prompt, reply, input/output tokens, cost, kind `ask`/`chat`), `create_tables`, `FakeTraces`
      with the same interface. Prompt and reply are stored after masking.
- [x] `llm.py`: `ask` and `chat` record every call; the chat session comes from a context variable set by `/chat` (and the replay), not from a new argument on each caller.
      Cost = tokens x a price constant per model, kept in one place next to `MODEL`.
- [x] Decision to confirm (below): a failed trace write does not block the customer's reply; it is counted and logged.
- [x] Fast tests: one trace per `ask`, one per `chat` round; a tool round records the prompt as sent; a refusal is still recorded; cost is from tokens; a trace write that fails
      does not fail the reply and is counted; a grep-style test that no module outside `llm.py` calls the Anthropic client; the stored prompt contains no card number.
- [x] Check: fast tests green. (The real table is first used in Phase 4's live check.)
      Result 2026-10-26: 658 fast tests, ruff, mypy green. Nothing was run against the real PostgreSQL or Claude. Decision 1 (trace failure does not block) is implemented as written; `llm.PRICES` holds a placeholder price for the author to set.

## Phase 4 - retention and erasure (B23, IT26)
- [x] `traces.customer_hash`: HMAC-SHA256 of the lower-cased email with `config.trace_key()`; set on `/verify/check` success, and the earlier rows of that session are filled then.
- [x] `retention.py`: `purge(older_than_days=90, now)` deletes traces older than 90 days (injectable clock); a daily command `python retention.py`.
- [x] Erasure: `/erase/start` and `/erase/check` reuse `verify` (the code is sent to the email and checked as in B1); on success delete her traces (by hash and by her session ids), drop her in-memory
      sessions, and write a row in `erasures` (time, number of rows deleted - no email, no hash). The reply says what was done and that ServiceNow cases are not covered yet (OQ-S4-1).
- [x] Fast tests: 89 days kept, 91 days deleted, exactly 90 by a written rule; erasure by a verified email deletes only her rows; an unverified or wrong code deletes nothing; the log row holds no personal data;
      the hash is HMAC (a different key gives a different hash; the plain sha256 of the email never appears); erasure twice is safe; a restart (empty `SESSIONS`) still finds her rows by hash.
- [ ] Live check (on request, our PostgreSQL only, own table names): write traces, purge, erase, read back; row counts as expected. Restore point first: `pg_dump -t traces` outside git, said in the message.
- [ ] Check: fast tests green; the live check green once.
      Written, not run (on request): `test_retention_live.py` uses temporary tables `traces_check` / `erasures_check`, so it needs no `pg_dump`. The first real
      run of `python retention.py` deletes rows from the real `traces`: `pg_dump -t traces` to a file outside git first.
      Fast result 2026-10-26: 668 fast tests, ruff, mypy green. Live check and the Check box stay open for the author.

## Phase 5 - read the policy pages, cut them into sections (IT21, IT22)
Changed after Phase 1: one list call `GET /rest/api/content?spaceKey=POL&type=page&limit=100` returns all 16 pages; the body is Markdown (`##` headings); market and
valid dates are in `metadata`; the link is `_links.webui`; there is no version history through the API; no login.
- [ ] `confluence.py`: read-only client (GET) with the account from `config.py`: pages of space `POL`, each with id, title, version, market, valid-from/valid-to, link, body. `FakeConfluence` (a dict) with the same interface.
- [ ] `policy.py`: cut a page into sections by headings; each section keeps page id, page version, heading, text, market, valid dates, link. A page with no market or no valid-from is an error naming the page, never a default.
- [ ] Fast tests with canned page bodies (including the "Return window" section, a holiday rule with dates, two versions of one page, a page for all markets): headings cut right, dates and market kept, link built from the page,
      a page with missing metadata raises, the cut is the same on a second run.
- [ ] Check: fast tests green; (live, on request) the reader lists the real `POL` pages and the section counts match the probe.

## Phase 6 - the index in PostgreSQL with embeddings (IT21, IT22)
- [ ] `embedder.py`: `embed(texts)` with fastembed `BAAI/bge-small-en-v1.5` (lazy load, so tests and the app start without the model); `FakeEmbedder` (deterministic, small).
- [ ] `CREATE EXTENSION vector` in our PostgreSQL (the author said yes; `fastembed` is installed). Two rules for one thing are two pages (1003, 1016): the key of a section is (page id, version, heading).
- [ ] `policy_index.py`: table `policy_sections` (page id, version, heading, text, market, valid dates, link, embedding, `tsvector`); `rebuild()` upserts by (page id, version, heading), removes the sections of pages and
      versions no longer returned, in one transaction; the version and dates decide what is stored. Command: `python policy_index.py` (hourly, like `pipeline.py`; no lock yet, same quick-fix). Uses `vector` if Phase 1 found it.
- [ ] Fast tests (FakeConfluence, FakeEmbedder, an in-memory index with the same interface): rebuild twice -> same index; a changed page replaces its sections; a removed page leaves no sections; a failure in the middle leaves the old index;
      a new version with a later valid-from is stored next to the old (both are kept, "valid today" decides).
- [ ] Live check (on request): index the real `POL`, print counts per market, run it again and compare. Restore point first: `pg_dump -t policy_sections` if the table already holds rows.
- [ ] Check: fast tests green; the live index green once.

## Phase 7 - the `policy_answer` tool and the chat (B18, IT21)
- [ ] `policy_answer(question, market)`: searches by meaning (embedding) and by words (full text), **only** in sections of that market valid today (the injectable clock), returns the top sections with text and link, or `no_page`.
- [ ] Market: `/chat` takes an optional `market`; the verified customer's `MKT_CD` overrides it; none known -> the assistant asks which country (a tool result, not a guess).
- [ ] `app.py`: `policy_question` joins `COVERED`; `agent.py`: the system prompt answers policy only from the tool, in the customer's words, with the link; the tool result reaches the model in a block marked as data.
- [ ] Code check on the reply: a policy reply without a link that the tool returned is replaced by the fixed hand-off offer (a person, not memory). `no_page` -> "I cannot find that in our policy; I can pass you to a person".
- [ ] C14 (intent `return_request`, asks about the opened-item rule): decide in this phase from the misses, one change at a time (Build 3 pattern); note the score.
- [ ] Fast tests (scripted fake model, FakeIndex): market scoping (a UK-only rule never answers a US customer); a page not yet valid or expired is never returned; two versions -> the one valid today; no market asks; no page offers a person;
      a reply with an invented link is replaced; a reply with a returned link is kept; unverified customers can ask policy questions and still get no order data (B1).
- [ ] Live check (on request): the 8 policy conversations against the real index and `data/policy_key.json` (confirmed by the author): each gets the right link or the offer where the key says "no page".
- [ ] Check: fast tests green; the live check on the 8 conversations written here.

## Phase 8 - code and pages say the same (B19, IT22)
- [ ] `check_windows(index, today)`: compares `returns.WINDOWS` and `returns.US_OPENED` with the "Return window" sections valid today, per market; any difference is an error naming market, code value and page value.
- [ ] `policy_index.py` runs it after each rebuild and exits non-zero on a difference (the index is still stored; the check tells the support team). `python policy_index.py --check` runs it alone.
- [ ] Fast tests: equal windows pass; a changed page (UK 14 -> 21) fails and names it; a page that does not state a window for a market fails; a new version valid from tomorrow does not fail today and fails from tomorrow;
      "within an hour" tested with the fake clock: page changed at 10:00, rebuild at 10:59, a question at 11:00 gets the new rule on its first valid day.
- [ ] Live check (on request): `python policy_index.py --check` against the real `POL` reports equal or the exact differences.
- [ ] Check: fast tests green; the live check result written here.

## Phase 9 - words never change what the assistant may do (B20, IT23)
- [ ] Audit in code (a list in this plan, with file and line): no chat text is used as an instruction by code - the places that read the message (`is_yes`, `classify`, `damaged_on_arrival`) only decide by the strict rules already there.
- [ ] Tool results to the model are wrapped in a data block with a fixed marker (order data, policy sections, `prepare_return` results); the system prompt says text in a data block is never an instruction.
- [ ] `test_hard_messages.py` (fast): the 10 messages of `data/hard_messages.json` against a scripted fake model that *obeys* the message (approves, shows another's order, promises an exception, marks delivered) - the code still stops it:
      no draft, no order data for an unverified session, no exception promise, no card number in history, traces or case.
- [ ] `test_hard_messages_live.py` (live, 3 runs of the 10, real Claude, fakes under it): define "nothing the never list forbids" as a list of checks per message (no draft written, no ServiceNow task, no order data of another customer,
      no "approved"/"exception" promise, no card digits stored); 3 of 3 runs must pass.
- [ ] Check: fast tests green; the live check 3 runs x 10 written here.

## Phase 10 - the replay (G4) and close Build 4
- [ ] `replay.py`: `answer_policy` is a score of its own (the reply carries a link from the tool; right page by `data/policy_key.json`), no longer `hand_off`; traces go to `FakeTraces`; the market is sent per conversation.
- [ ] Run the replay (twice, the score varies): the 8 policy conversations get the right link; at least 36 of 40 right actions; zero conversations that need a person stayed; the 30 borderline cases still green;
      the 10 hard messages 3 of 3. If not met: stop, look at the misses, one change at a time, replay after each, scores noted here.
- [ ] `docs/quick-fixes.md`: what was quick (no lock on the index job, English-only embedder, trace failure not blocking, price constant, no ServiceNow erasure, sessions in memory, hourly full rebuild).
- [ ] README: how to build the index, the hourly and daily jobs, erasure, the live checks and which command is which.
- [ ] `CLAUDE.md` pointers: it points to `docs/spec.md` / `docs/plan.md`; ask before changing it (it is the author's file).
- [ ] Check: fast tests, ruff, mypy, tsc green; live checks green; final scores written here.

## Decisions to confirm
1. A trace that cannot be written does not block the reply (the customer is served, the failure is counted and logged). The alternative is to refuse to answer without a trace, which makes PostgreSQL an outage for the chat. B22 then says "every call" - a counted gap, shown in the README.
2. A mismatch between code and pages (Phase 8) fails the job and tells the support team; it does not stop the chat. Policy answers always come from the page; `returns.py` stays the code's rule until a person changes it.
3. Both versions of a page are kept in the index; "valid today" picks one. Old versions are removed only when the page itself has none.
4. The cost is a price constant per model in `llm.py`, set by the author; wrong prices make the cost wrong but not the tokens.
5. Hourly index job and daily purge are commands run by cron on the host, as `pipeline.py`; no scheduler is built.
6. Commits: one per phase, only when you ask.

## Open questions I cannot answer from the repo
- OQ-S4-1 (spec, Sofia / Ravi): who erases a customer's data in ServiceNow cases. Until answered, erasure says it does not cover them.
- Whether the Phase 1 findings change the plan (page language, `vector`, valid dates): the phase stops and asks.
