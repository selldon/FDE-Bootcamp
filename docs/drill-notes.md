# Drill notes - the night with no carrier file (27 Oct 2026)

Phase 7 of `docs/plan-golive.md`. All times UTC, 27 Oct 2026, wall clock. The simulated clock of the service was pinned to
2026-10-23T05:00:00+00:00: the carrier's file for the 23rd never came.

## Times
| Time | What |
|---|---|
| 12:53:05 | Restore point taken: `backups/product-2026-10-27-before-drill/` (all 10 tables, `CLOCK_AND_STATE.json`); git `2e2e5bc` |
| 13:00:12 | Drill day built and committed (`73e62e0`) |
| 13:00:49 | The service restarted by the team, pinned to 2026-10-23T05:00:00+00:00 |
| 13:01:56 - 13:05:07 | Drill day 15 ran: 12 assistant conversations (155 of 165) |
| **13:07:32** | **The assistant was switched off from the page** (`golive_settings.changed_at`, `on = false`). Seen from the page's alert for day 15 |
| 13:13:02 | Fix committed (`5764f04`) |
| - | Replays run on the new code (below) |
| *to fill* | The assistant switched on again: take the time from the switch row (`changed_at`) |

**How long the assistant was off:** from 13:07:32 until the switch-on time above (to fill when the team switches it on). The
chats between 13:05:07 (the last drill chat) and the switch-off had no new customers: all traffic was simulated.

## What happened
No file for the 23rd. The order store still held the load of the 22nd. At 05:00 on the 23rd the 22nd's news was 29 hours old; the
tools' rule (IT14) called news stale only after 30 hours counted from the start of its day, i.e. after 06:00. So 7 of the 8
undelivered parcels were "fresh", the tools gave their dates, and the assistant gave yesterday's status as current.

- **Result of day 15:** 8 of 12 chats confidently wrong (67 %, interval 39 % to 86 %); the 3 delivered control orders were fine; the
  one parcel with news from the 15th was already stale and the guard fired. The page showed the alert (`alert_days [8, 15]`).
- **Of the 8:** 4 contradicted the carrier's real 23rd status (out for delivery where the parcel had been delivered); 4 only quoted the
  22nd's date for a parcel that was still on its way. The rule (D3) counts both.
- **Cause:** the freshness rule measured hours since the news date, not whether the night file had arrived. A missing file was
  invisible until 06:00 UTC, and the hourly load check was silent as well (the 30-hour news check).

## The rule (decided with the team)
The carrier's night file is expected by 03:00 UTC. After that, yesterday's news is old: no status or date as fact, and the reply
offers a person. The hourly check also says the file is missing. The hour is a working value: **Ravi Menon's team confirms it (OQ-5).**
`checks.FILE_EXPECTED_BY`; `docs/requirements.md` OQ-5; `docs/spec-2.md` IT13, IT14 and the decision row of 2026-10-27.

## Tests (written first, failed before the fix, pass after)
- `test_checks.py`: the expected news date flips after 03:00:00 UTC (03:00:00 sharp is still on time); yesterday's news is old after,
  today's never; the clock is read in UTC; the hourly check names the missing file and is quiet when it is not due or is there.
- `test_tools.py`: yesterday's news gives its date until 03:00:00 and no date plus `offer_person` after; **the drill morning (05:00,
  29 hours) is old**; two-day-old news is old at any hour; delivered parcels stay final.
- `test_pipeline.py`: a missing night file stops the hourly run, the message says `carrier-2026-10-23.csv is missing`, nothing is written;
  03:00 sharp and a run with the file of the day still load.
- The fast tests' clock moved to 02:00 on the 22nd (before the file is due) so their news stays current; the two 30-hour tool tests
  became 03:00 tests. 1,015 fast tests pass.

## Replay results (on the fixed code, live model, nothing real written)
- **The 40 labeled conversations** (`replay.py --gate`, pinned to 05:00 on the 22nd, where the store's news is current): **38 of 40, gate
  pass.** Misses C17 and C26, the same two as the Phase 6 baseline (goal 36). Zero conversations that need a person stayed with the
  assistant; zero drafts written.
- **The drill day's 12 chats** (`golive_sim.py --replay-drill 15`, pinned to 05:00 on the 23rd, the code of `5764f04`): **0 of 12
  confidently wrong**, against 8 of 12 on the live day (interval now 0 % to 24 %: 12 chats cannot prove zero). The system prompt was
  not changed; the replies word the old news as old and offer a person.
- **The mechanism, which does not depend on the model:** at 05:00 on the 23rd the guard fires for all 8 undelivered parcels (before:
  1 of 8); at 02:59 it fires for 1 (the file is not due); at the CI pin on the 22nd for 1; delivered parcels are never touched.

## Also seen (not measured by any line)
In several drill and replay chats the assistant again told the customer it had not checked when the traces show a lookup before every
reply (see `docs/plan-golive.md`, "Observed in week two"). The replay run of the drill chats showed it once more (DS-20502). Not fixed.

## Still open
1. The service must be restarted on the new code before the assistant is switched on: the running process was started before `5764f04` and still has the 30-hour rule.
2. The clearing day (day 16, 10 assistant conversations, 165 of 165) under the same night, after the switch-on, so that the page's latest-day alert clears.
3. The hour 03:00 UTC: Ravi Menon's team (OQ-5).
