# Plan: the pilot dashboard (Day 10)

Build from `docs/brief-dashboard.md`. Work one phase at a time, tick the boxes, stop at each **Stop**.

## Context

Shadow mode answers every new live chat into `shadow_chats` and nobody sees it. Lena and Marco need a page with fixed numbers
and a way to mark answers. Reading the code showed four things the brief only hints at:

1. `shadow.py:237` stores `"intent": None` for every row. The worker calls `answer()` directly and never runs `classify()` or the
   hand-off gate from `app.py:158-165` (needs_human / damaged / intent not in `COVERED`). Shadow actions are therefore too
   optimistic: a chat that live would hand to a person gets an answer in shadow.
2. Tokens and cost are not stored: they go into `FakeTraces` (`shadow.py:229`) and are thrown away.
3. `shadow_answer` stores the raw message and answer. The chat service masks card numbers first (`app.py:142`, `:175`), shadow does not.
4. The widget is one `App.tsx` with no router, and nginx proxies only `/(chat|verify|erase)`.

## Decisions (yours)

- **Intent:** share the gate. One function decides the hand-off reason; the chat service and the worker both use it. The worker calls `classify()` through `llm.py` and stores the intent.
- **Who marked:** a name typed on the page (kept in the browser) is stored with each mark. The internal network is the only access control; logged as an open point (a real login comes with the public address on day 11).
- **Old rows:** kept as they are (intent NULL, no tokens). Every table shows an "unclassified" / "unpriced" line, so every share divides by the same total. No backfill, no overwrite.

## My defaults (say if you disagree)

- **Resolved** = the gate passes and the action is `give_status`, `reply` or `start_return`. Only `hand_off` is not resolved. A started return counts: the request is handled without a person, only the money waits for one (your change).
- **Success criterion** = resolved `order_status` chats / all `order_status` chats, compared with 50%. Chats without an intent are listed apart, never dropped from totals.
- **Checked sample** = chats with at least one mark; the latest mark per chat counts. A person re-marking replaces their own mark (`marked_at` updates).
- **Confidently wrong** = verdict `wrong` and `sounded_sure = true`.
- **Cost** = stored tokens priced by `llm.cost(MODEL, ...)` at read time (prices stay in `llm.py`, a price change reprices the page). Rows with no tokens are counted as unpriced, never priced at 0.
- **How sure** = 95% Wilson interval on the checked sample, computed in code; the third sentence says the range and the sample size.
- **Random list** = unmarked chats that have an agent reply, ordered by `md5(number || current_date)`: random across days, stable within a day, no server state.

## Phase 0 - branch and plan (offline)
- [ ] Copy this plan to `docs/plan-dashboard.md` and commit it on branch `dashboard`. Then stop: the phases run one at a time, on your word.
**Check:** `git status` is clean and the commit holds only that file.

## Phase 1 - one gate for both (offline)
- [x] `intent.py`: move `COVERED` here and add `handoff_reason(intent) -> str | None` returning `needs_human`, `damaged`, `not_covered` or None. `app.py` calls it (same order, same reason strings, same `open_case` labels).
- [x] Test: each reason, the order when several apply, None for a covered intent. The existing `test_chat.py` passes unchanged.
**Check:** `python -m pytest -q -m "not live"`, ruff, mypy. **Stop.**

## Phase 2 - the worker stores what the page needs (offline)
- [x] `shadow.py`: columns `input_tokens int`, `output_tokens int` added with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` next to the CREATE (additive, old rows get NULL); `FIELDS`, `FakeShadowStore`, and the column test in `test_shadow.py:64-71` follow.
- [x] `shadow_answer`: set the fake sink before anything, `classify(mask_cards(message))`, store `intent`; if `handoff_reason` is set the action is `hand_off` and `answer()` is not called (the reply comes from `handoff.open_case` against the fake ServiceNow, as live, so the text is the live text); else `answer()`. Tokens = sum over `fake_traces.rows` (includes the classify call). Mask message and answer before storing.
- [x] Tests: a covered chat stores its intent and tokens; an angry and a damaged message store `hand_off` with no `answer()` call; a card number in the message is stored masked; nothing is written to the real sinks (existing test keeps passing).
**Check:** fast tests, ruff, mypy. Then you run `python shadow.py --once` against the sandbox (it calls Claude and the ServiceNow reader; I do not start systems) and I look at `python shadow.py report` for one new row with intent and tokens. **Stop.**

## Phase 3 - marks and the sample (offline)
- [x] `shadow_marks(number text, marker text, marked_at timestamptz, verdict text CHECK in same|better|worse|wrong, sounded_sure boolean, PRIMARY KEY (number, marker))`. `sounded_sure` only with `wrong` (CHECK). Store methods `mark`, `marks`, `sample(n, day)`; same on `FakeShadowStore`. Rejected marks: unknown number, empty name, bad verdict.
- [x] Tests: upsert keeps one mark per (chat, person) and moves `marked_at`; `sounded_sure` refused with other verdicts; sample excludes chats without an agent reply and already-marked ones; same day same list, next day another.
**Check:** fast tests, ruff, mypy. **Stop.**

## Phase 4 - the numbers (`pilot.py`, offline)
- [ ] `numbers(store, now) -> dict`: one function, plain data, no model, no HTML. Per day, per market, per action; per intent with an "unclassified" row; checked verdict counts with the sample size beside them; tokens and cost (per chat, per resolved chat, unpriced count); the baseline constants ($7, 4 min, $0.99, 50%) in one place at the top.
- [ ] Tests: **every breakdown sums to the same total** (days, markets, actions, intents); a market of None is its own row; an empty store gives zeros and no division error; a row without tokens is unpriced, not free; the numbers are identical on two calls.
**Check:** fast tests, ruff, mypy. **Stop.**

## Phase 5 - the words for Lena (offline)
- [ ] `sentences(numbers) -> list[str]`, three fixed templates: (1) where we are against the criterion, with the base and the line "an estimate: no customer reacted in shadow mode"; (2) cost per resolved chat against $7 / $0.99; (3) how sure, from the Wilson interval and the checked sample. Plain wording when the base is 0 ("not enough yet", never a percentage of nothing).
- [ ] Tests: exact strings for a small fixed case, the empty case, and a case where the sample is too small to say.
**Check:** fast tests, ruff, mypy. **Stop.**

## Phase 6 - the API (offline)
- [ ] `app.py`: `GET /api/pilot` (numbers + sentences), `GET /api/pilot/sample`, `POST /api/pilot/mark`. Store injected so tests use `FakeShadowStore`. Payloads never include `opened_for` (the customer's email); message and answer are masked again on the way out (covers old rows).
- [ ] `widget/nginx.conf`: add `api` to the proxied prefixes.
- [ ] Tests (`TestClient`): numbers shape, sample, a mark stored and returned, bad verdict is a 422, no email in any payload, a card number in an old row comes out masked.
**Check:** fast tests, ruff, mypy. **Stop.**

## Phase 7 - the page (offline, then I look at it)
- [ ] `widget/src/Pilot.tsx` (new), shown by `App.tsx` when `location.pathname === "/pilot"`; no router dependency. Plain tables: days, markets, actions, intents, checked sample with its size, cost and baseline, the three sentences under the numbers, the side-by-side list with the four verdict buttons, the "sounded sure" tick on `wrong`, a name field kept in `localStorage`. Every rate shows its base. A visible note: "would have resolved is an estimate".
- [ ] It only reads, except `POST /api/pilot/mark`.
**Check:** `cd widget && npx tsc -b` and `npm run build`. I open the page in the browser against the local chat service with the fake data, screenshot it, and mark one chat. **Stop.**

## Phase 8 - retention, notes, ticks (offline)
- [ ] `retention.py`: the 90-day purge also covers `shadow_chats` and the marks of the purged numbers (read `retention.py` first; a test with the fake store). The first real run deletes rows, so before it I stop and you take a `pg_dump` of the `product` database; the code itself deletes nothing until run.
- [ ] `docs/quick-fixes.md`: self-declared names on marks; sample cost of the extra `classify` call per shadow chat; old rows stay unclassified.
- [ ] README: a "Pilot page" section (address, what it shows, who may open it).
- [ ] Tick this plan with what was seen.
**Check:** `python -m pytest -q -m "not live"`, ruff, mypy, `npx tsc -b`; pre-commit is not skipped. **Stop.**

## Rules for the whole plan
- Every model call goes through `llm.py`; the page and `pilot.py` make none. The numbers come from code and SQL.
- The worker writes nothing to ServiceNow, Ledgerline or the real trace table. The only writes are our own `shadow_chats` and `shadow_marks`.
- A refund is only ever a draft that a person approves; shadow mode makes none.
- Customer messages stay inside DemoStore: no public address, no email in any payload, card numbers masked.
- I never start, stop or change the sandbox systems. The only SQL that changes or deletes existing rows is the retention run, behind a dump.
- Fast tests keep passing; pre-commit is never skipped; shortcuts go to `docs/quick-fixes.md`.
- Phases 1-8 add or change code only; no restore point is needed until the first real retention run.

## Verification, end to end
1. Fast tests, ruff, mypy, tsc all green.
2. `python shadow.py --once` stores a row with intent, a gated action and tokens.
3. Open `/pilot` locally: tables add up to one total, the three sentences read correctly, a mark is stored with name and time.
4. Search every payload and the page for an email address or an unmasked card number: none.
