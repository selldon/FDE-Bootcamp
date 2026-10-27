# Go-live - plan (Day 11)

Builds `docs/brief-golive.md`: the assistant goes live for "where is my order" for 5 % of visitors, the rest are a control
group that goes to a person in ServiceNow, two simulated weeks, a drill, then 25 % and returns (drafts only).
Each phase ends in a check we can run: the fast tests (`python -m pytest -q -m "not live"`; pre-commit also runs ruff,
mypy, tsc) or a named command. Tick boxes as tasks are done. One phase at a time; stop after each one.

## Decisions made (with the user)
- **Table**: a new `golive_chats` table (additive, `CREATE TABLE IF NOT EXISTS`, like `shadow.tables()`). `shadow_chats` and the shadow pilot page stay as they are.
- **Drill**: run the real code first on the night with no carrier file. No planted fault. If it gives yesterday's status, the alert fires and we do the full off -> test-first fix -> replay -> on cycle. If it holds, we record that and still time an off/on switch drill.
- **Outcomes**: control outcomes and ratings come from seeded rules in one `sim_assumptions.json` (repeat contacts are computed from the old ServiceNow chats). No extra model calls.
- **Signed margins (Lena)**: unanswered at most 3 points worse than control; rating at most 0.2 lower (1-5 scale).
- **Customers**: seeded scripts from the profiles (a question + 1-3 follow-ups, true order status known). Only the assistant group's turns call Claude, through `/chat` and `llm.py`.

### Decisions from week one (27 Oct 2026, with the user) - for Lena
Week one's first scoring said 19 of 39 assistant order-status chats were confidently wrong. Reading them, 18 of the 19 were the scorer's mistakes, not the assistant's, and the page showed "holds" only because the labels never reached it. These rules came out of that.
- **The truth is the night the service loaded.** Answers are scored against the carrier's newest nightly file in the carrier folder (the 22nd for week one, the same file the service reads), not the repo's `data/carrier.csv` (the 21st, one night behind). Against the old file, correct answers about the 22nd were marked wrong.
- **Only real month words are dates.** "Oct", "October", "Sept." count; a product name such as "Nova 32" is not "Nov 32". It had marked correct answers wrong whenever a reply named a Nova monitor.
- **Partly shipped orders.** A reply about a partly shipped order is right when every fact it gives matches the carrier's file of that night, and it names the mismatch (the order still says part shipped) instead of hiding it. Still wrong: "delivered" with the mismatch hidden; "delivered" when the carrier does not show every parcel delivered; a date the file does not have. (`score_reply` in `golive_sim.py`, with tests for each case.)
- **Repeat contact is not measured.** The old ServiceNow chats come from 15 customers: "the same customer wrote again within 7 days" is true of 0.99 of them, "the same customer about the same order" of 0.003. Neither is a baseline and none is invented. The page shows the row as not measured, with that reason; the table holds no repeat values; it is not one of the rollback lines.
- **A zero that measured nothing is not a pass.** The simulator writes its outcome labels (rating, confidently wrong, needs a person, control outcome) into `golive_chats` after every day, because the page reads only that table. A rescore stops if an assistant chat that should have replies has none, instead of scoring it right.
- **A failed model call is a hand-off, not an error.** The chat goes to a person with the chat so far and stays in the assistant group, so the lines count it.
- **A negated status is not a claim (week two).** "It isn't still on its way" followed by the right status was scored as claiming "on the way" and flagged two correct answers. A claim now counts only when no negation sits just before it, and a negation never hides a claim that is really made (tests for both).
- **A rule is not softened after it fails (user, 27 Oct).** The partly-shipped rule above stayed exactly as written when week two's day-8 chat failed it: the reply gave right facts and did not name the part-shipped status, so it counts as wrong. The line reads what it reads, and Lena decides with that number.

### Observed in week two, not measured by any line
Two chats where the assistant told the customer something untrue about its own process after the customer pushed back. The traces show a `find_order` and `delivery_status` lookup before every reply in both chats, so it had checked each time; the facts it gave stayed right.
- Day 8, DS-20468, chat `ace2921e-5bd9-4e3c-822b-3c0e6b61d297`: "I should have checked the system before my last message" and "I should have done that before my earlier replies" - it had looked the order up before each reply.
- Day 12, DS-20570, chat `361926db-9c9b-4dce-ad1c-4167564e70e2`: "I said I had just checked again, but I hadn't" - it had (lookups at 12:37:52 and 12:37:53 before that reply).

## Where we start (read)
- `app.py`: `/chat` has `session_id`, no visitor id and no group; `get_session` keeps sessions in memory; `/api/pilot*` serve the shadow page from `ShadowStore`.
- `handoff.open_case` -> `servicenow.create_case` (POSTs a case). The live-queue stand-in is `POST /api/now/table/interaction` (page `/live`, account `fde_tasks`); to check in phase 2 that `servicenow.CASES` is that table.
- `pilot.py` has `wilson()`, `MIN_SAMPLE`, `is_resolved`, `chat_cost`, `PERSON_COST`, `PERSON_MINUTES`; reuse them, do not copy.
- `tools._stale` refuses carrier news over 30 h (`checks.MAX_NEWS_AGE`); `config.now()` / `DEMOSTORE_NOW` pin the clock. `docs/quick-fixes.md` lists open gaps (news overwritten with NULL when a parcel is missing from the newest file; `newest_rows` reads one file only) - likely drill suspects.
- Simulator inputs: `sandbox/data/hard_profiles.json` (profiles with `knows/wants/tone/patience` and `expect`), `orders.json`, `carrier.csv`, ServiceNow stand-in's 2,040 old chats (no rating, no resolved flag).
- Gap to keep in view: 5 % of visitors means ~1,500 visitors for 75 assistant conversations a week. The cap is 150 assistant conversations in all, so the control group is large and cheap, the assistant group small. Daily samples are tiny (about 10 chats), so one wrong answer is already over "1 in 100". Decision (user): the confidently-wrong line is judged on the day and over the whole week; the page shows both, with interval and n.

## How we work
Phases 1-5 run one at a time, stopping after each. Phases 6-8 (the two weeks, the drill, the report) we run together.

## Phase 1 - the launch switch and the group (brief item 1)
- [x] `golive.py`: tables `golive_settings` (one row: `share`, `intents[]`, `on`, `changed_at`) and `golive_chats`; `group_of(visitor_id, share)` from a keyed hash of the visitor id into 10,000 buckets, so the group never changes, and widening 5 % -> 25 % only adds visitors to the assistant group, never removes one.
- [x] `FakeGoLiveStore` with the same interface (as `FakeShadowStore`); `GoLiveStore` over PostgreSQL. Every row has a `simulated` flag and `sim_day`.
- [x] Fast tests: same id -> same group every time; about 5 % of 10,000 ids; 25 % is a superset of 5 %; off or an intent not live -> "person"; settings read at every request (no cache, so no deploy).
- [x] Check: fast tests pass. Tables are new, so no restore point; take a `pg_dump` of `product` first anyway before the first run that writes rows (phase 6).

## Phase 2 - the chat service routes by group (items 1, Limits)
- [x] `ChatIn` gets `visitor_id` (and `simulated`, default false). New chat: switch off or intent not live -> hand off within the request via `handoff.open_case`; control -> the live queue (decide in code whether `create_case` or the interaction POST is right, one helper in `servicenow.py`); assistant group -> today's `_chat`.
- [x] Every chat writes one `golive_chats` row (visitor, group, intent, outcome, handed_off, tokens, cost, simulated, sim_day).
- [x] Switch off never loses an open chat: a chat already open is handed to a person with its transcript on its next message, never dropped. Tested with a chat open when the switch flips.
- [x] No refund is paid by the assistant; at 25 % returns still go only through `refunds` drafts (test that no code path writes except the draft).
- [x] Check: fast tests pass, including the off-switch and open-chat tests; `grep -n "client.messages" *.py` still finds only `llm.py`.

## Phase 3 - the simulator and its truth (item 2)
- [x] `golive_sim.py` (repo root, imports `config`, no new container): seeded visitors for 14 days, a day, a question and 1-3 follow-ups from the profiles; each carries the true order status. Output carries `simulated: true` on every row.
- [x] `sim_assumptions.json`: control resolve/hand-off/unanswered/rating rates per intent, assistant rating rule, repeat-contact window (7 days). Control repeat contacts computed from the old chats.
- [x] Cap: at most 150 assistant conversations; the runner stops and says so. A `--dry-run` prints the plan (visitors, groups, expected model calls, cost estimate from `llm.PRICES`) and writes nothing.
- [x] Scoring: "confidently wrong" = a status given as fact that differs from the true status or its date, counted by code against the truth.
- [x] Check: fast tests with a fake model: same seed gives the same traffic; the cap holds; a wrong status is counted; every row is labelled simulated; `python golive_sim.py --dry-run` runs without Claude.

## Phase 4 - the numbers and the rollback lines (items 3, signed lines)
- [x] `golive.numbers(store, now)` in the style of `pilot.numbers`: per group resolved, handed off, left without an answer, repeat contacts in 7 days, rating, cost per contact; the difference with its 95 % interval (reuse `pilot.wilson`; difference interval for two proportions; a mean difference for rating) and both sample sizes.
- [x] `lines(data)`: confidently wrong > 1/100, judged on the day's sample (the alert) and also over the whole week so far (a day of ~10 chats cannot measure 1 in 100; both are shown on the page, the week with its interval and n); hand-off < 95/100 of chats that need a person; chats left without an answer more than 3 percentage points worse than control, or the rating more than 0.2 lower than control on the 1-5 scale (margins signed by Lena; kept as constants in `sim_assumptions.json`, tests pin them); "all hold for two weeks" check. No model call.
- [x] Fast tests: each line at, just below and just above its limit; a group with 0 chats gives "not enough yet", never a division error.
- [x] Check: fast tests pass.

## Phase 5 - the comparison on the pilot page (item 3)
- [x] `GET /api/golive` and the switch (`GET/POST /api/golive/switch`, for the page and for the drill); `widget/src/GoLive.tsx` next to `Pilot.tsx`: both groups side by side, difference, interval, n, "holds / does not hold", an alert banner, and a banner "Simulated traffic" on the page.
- [x] Check: fast tests of the API with the fake store, `tsc` clean, and one look at the page in the browser with seeded fake rows.

## Phase 6 - the two simulated weeks (item 2) - asks before it spends
- [x] Restore point first: `pg_dump` of `product` to `backups/` and say so. Then show the dry-run cost and wait for a yes.
- [x] Run week 1 and week 2 at 5 % (live: Claude calls, at most 150 assistant conversations) against the running service, one sim day at a time, rows labelled simulated.
- [x] Check: the page shows both groups for 14 days; row counts per day add up; assistant conversations <= 150; no line is hand-edited.

## Phase 7 - the drill (item 4) - its own phase
- [ ] Restore point: dump of `product`, and the time on the clock noted. Add one sim night with no carrier file (`DEMOSTORE_NOW` pinned to that day; the file simply missing, as `newest_rows` would see it).
- [ ] Run that day's assistant chats against the real code. Read the numbers: did a stale status go out as fact?
- [ ] If yes (alert): switch the assistant off from the page (time it; new chats go to a person within seconds), write the failing test first (`test_tools.py` / `test_pipeline.py`), fix the cause (start from the quick-fixes rows), replay `data/conversations.json` and the bad day's chats with `replay.py`, then switch on. If no: record that the guard held and still time off -> on.
- [ ] Write down how long the assistant was off, in `docs/drill-notes.md` (times, cause, test, replay result).
- [ ] Check: the new test fails before the fix and passes after; fast tests pass; `python replay.py` result recorded; the page shows the alert, then clears.

### Phase 7 - the night with no carrier file, planned (27 Oct 2026) - PROPOSED, decisions D1-D4 to confirm before the run
**Restore point (done):** `backups/product-2026-10-27-before-drill/` - all 10 tables of `product` (row counts checked: `golive_chats` 2,453, `traces` 1,007, `orders` 33, `parcels` 33, ...), `CLOCK_AND_STATE.json`, and copies of the simulator log, `cases.jsonl`, `outbox.jsonl`. Noted there: wall clock 2026-10-27 12:53 UTC; the service pinned to 2026-10-22T05:00:00+00:00; the switch on at 5 % for `order_status`; git `2e2e5bc`. It is a data-level CSV dump (`pg_dump` is not installed here). The ServiceNow stand-in cannot be backed up from here: the drill's hand-offs will add cases to it.

**The night.** The carrier's file for the 23rd never comes. The SFTP server already holds only `carrier-2026-10-20/21/22.csv`, so nothing is added or removed. The order store keeps the load of the 22nd. The service's clock is pinned to the morning of the 23rd.

**What the real code does (read from the code, not yet run).** `tools._stale` counts a parcel's news age from the start of the news day and calls it stale beyond 30 hours; delivered parcels are final. News dated the 22nd turns stale at **06:00 UTC on the 23rd**. At 05:00 UTC it is 29 hours old: 7 of the 8 undelivered parcels are still fresh (the 8th has news from the 15th and is already stale), the date is not removed, and the pipeline's own check stays silent as well. After 06:00 UTC all 8 are stale: the tools drop the date and set `offer_person`. So at the usual morning pin the assistant is expected to give the 22nd's status as current. That would be the finding of the drill, not a planted fault.

**What the service needs.**
1. One restart with `DEMOSTORE_NOW=2026-10-23T05:00:00+00:00` (D1). Nothing else: no reload, no new file, no schema change; the `golive` tables exist, the switch stays on. On the deployed server the pin lives in `deploy/server.env`.
2. Do not run `python pipeline.py` against the live SFTP with that pin: at 05:00 it would re-load the 22nd file and stamp it as loaded on the 23rd; after 06:00 it stops with "30.0 hours old" and writes nothing.
3. After the fix, one more restart with the same pin for the clearing day (D4).

**What the simulator needs (code, test first, after the decisions).** A drill day beyond day 14 with its own traffic, its own cap ceiling and its own truth; `golive.numbers` must report days after 14 as drill days and keep them out of the week and two-week window, otherwise the window slides to days 2-15 and the Phase 8 numbers are mixed with a day that is broken on purpose.

**Decisions.**
- **D1 - the pin.** 05:00 UTC on the 23rd (recommended: the usual morning; predicted to fail) or after 06:00 UTC (predicted to hold: the guard the unit tests already cover).
- **D2 - the traffic.** The default generator gives day 15 only 1 order-status chat on an order that is not delivered, so it would test almost nothing (14-day average: 46 %). Proposed: 12 assistant conversations, all order status, 9 on orders with an undelivered parcel, 3 on delivered orders as a control (the guard must leave those alone).
- **D3 - the truth for the night.** A hidden file for the 23rd (what the carrier would have sent: some parcels moved on), kept out of the SFTP folder and used only for scoring. A reply is wrong when it states a status or date that differs from it, and a hedge ("the news is old") excuses it, as everywhere else. The partly-shipped rule and the negation rule are unchanged.
- **D4 - the clearing day.** After the fix, day 16 under the same night, 10 assistant conversations, so the page's latest-day alert can clear. Cap: 143 used + 12 + 10 = 165 = 150 + the 15 allowed. About $0.4 per day in model calls.

## Phase 8 - the decision and the report (item 5)
- [ ] If all lines hold for the two weeks: switch to 25 % and add `return_request` to the live intents (drafts only; the writer account's only use is still `LL_RTN_REQ_STG`).
- [ ] `docs/week-2-report.md` from the page's numbers (script, not by hand): operator hours saved a week (resolved assistant chats x `PERSON_MINUTES`, scaled from the 5 % sample), and what 100 % would mean, with the assumptions (simulated traffic, seeded ratings, scale-up, tiny samples) said out loud.
- [ ] Write the new quick fixes into `docs/quick-fixes.md`.
- [ ] Check: fast tests pass; every number in the report matches `GET /api/golive`; the report says "simulated" in its first lines.

## Limits kept throughout
Simulated everywhere (page, report, every row). Switch never needs a deploy. Every model call through `llm.py`; numbers from code and SQL. Restore point before any change to stored rows. Containers in `sandbox/systems/`, Ledgerline and the carrier's server are never started, stopped or changed; Ledgerline writes stay limited to the return draft.

## Verification end to end
`python -m pytest -q -m "not live"`; `python golive_sim.py --dry-run`; then phases 6-7 against the running service; open the page and check the banner, both groups, the alert and the report numbers.
