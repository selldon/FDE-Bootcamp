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
- [ ] `golive.numbers(store, now)` in the style of `pilot.numbers`: per group resolved, handed off, left without an answer, repeat contacts in 7 days, rating, cost per contact; the difference with its 95 % interval (reuse `pilot.wilson`; difference interval for two proportions; a mean difference for rating) and both sample sizes.
- [ ] `lines(data)`: confidently wrong > 1/100, judged on the day's sample (the alert) and also over the whole week so far (a day of ~10 chats cannot measure 1 in 100; both are shown on the page, the week with its interval and n); hand-off < 95/100 of chats that need a person; chats left without an answer more than 3 percentage points worse than control, or the rating more than 0.2 lower than control on the 1-5 scale (margins signed by Lena; kept as constants in `sim_assumptions.json`, tests pin them); "all hold for two weeks" check. No model call.
- [ ] Fast tests: each line at, just below and just above its limit; a group with 0 chats gives "not enough yet", never a division error.
- [ ] Check: fast tests pass.

## Phase 5 - the comparison on the pilot page (item 3)
- [ ] `GET /api/golive` and the switch (`GET/POST /api/golive/switch`, for the page and for the drill); `widget/src/GoLive.tsx` next to `Pilot.tsx`: both groups side by side, difference, interval, n, "holds / does not hold", an alert banner, and a banner "Simulated traffic" on the page.
- [ ] Check: fast tests of the API with the fake store, `tsc` clean, and one look at the page in the browser with seeded fake rows.

## Phase 6 - the two simulated weeks (item 2) - asks before it spends
- [ ] Restore point first: `pg_dump` of `product` to `backups/` and say so. Then show the dry-run cost and wait for a yes.
- [ ] Run week 1 and week 2 at 5 % (live: Claude calls, at most 150 assistant conversations) against the running service, one sim day at a time, rows labelled simulated.
- [ ] Check: the page shows both groups for 14 days; row counts per day add up; assistant conversations <= 150; no line is hand-edited.

## Phase 7 - the drill (item 4) - its own phase
- [ ] Restore point: dump of `product`, and the time on the clock noted. Add one sim night with no carrier file (`DEMOSTORE_NOW` pinned to that day; the file simply missing, as `newest_rows` would see it).
- [ ] Run that day's assistant chats against the real code. Read the numbers: did a stale status go out as fact?
- [ ] If yes (alert): switch the assistant off from the page (time it; new chats go to a person within seconds), write the failing test first (`test_tools.py` / `test_pipeline.py`), fix the cause (start from the quick-fixes rows), replay `data/conversations.json` and the bad day's chats with `replay.py`, then switch on. If no: record that the guard held and still time off -> on.
- [ ] Write down how long the assistant was off, in `docs/drill-notes.md` (times, cause, test, replay result).
- [ ] Check: the new test fails before the fix and passes after; fast tests pass; `python replay.py` result recorded; the page shows the alert, then clears.

## Phase 8 - the decision and the report (item 5)
- [ ] If all lines hold for the two weeks: switch to 25 % and add `return_request` to the live intents (drafts only; the writer account's only use is still `LL_RTN_REQ_STG`).
- [ ] `docs/week-2-report.md` from the page's numbers (script, not by hand): operator hours saved a week (resolved assistant chats x `PERSON_MINUTES`, scaled from the 5 % sample), and what 100 % would mean, with the assumptions (simulated traffic, seeded ratings, scale-up, tiny samples) said out loud.
- [ ] Write the new quick fixes into `docs/quick-fixes.md`.
- [ ] Check: fast tests pass; every number in the report matches `GET /api/golive`; the report says "simulated" in its first lines.

## Limits kept throughout
Simulated everywhere (page, report, every row). Switch never needs a deploy. Every model call through `llm.py`; numbers from code and SQL. Restore point before any change to stored rows. Containers in `sandbox/systems/`, Ledgerline and the carrier's server are never started, stopped or changed; Ledgerline writes stay limited to the return draft.

## Verification end to end
`python -m pytest -q -m "not live"`; `python golive_sim.py --dry-run`; then phases 6-7 against the running service; open the page and check the banner, both groups, the alert and the report numbers.
