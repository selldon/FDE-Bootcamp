# Runbook: the DemoStore support assistant

For the person on call. **Nothing here sends a message by itself.** A job that fails prints to its own output, a container that
is unhealthy shows it only in `docker compose ps`, a red check in GitHub is an email to whoever last changed the schedule, and the
alert on the go-live page shows only while someone has the page open. Sending cron errors, container health and CI email to the
person on call is the job of the Director of E-commerce Engineering's team, to be done before we leave. It is the first gap in
[Gaps](#gaps), and until it is done this runbook is read after someone notices, not when something happens.

**Every role named in this runbook (in "Who next", in the gaps and in the owners) is proposed.** Each is to be confirmed with the
Director of E-commerce Engineering and the Head of Customer Support at the handover meeting; a role that says no is replaced here.

Seven entries, one per alert that a person acts on. Each has the same parts: what it means and what customers feel, the first
check, how to act, how to see that it worked, who next.

## Before you start

Two places run these commands: the server (`/opt/demostore`, reached from the server itself) and a laptop with the stack up
(`docker compose up -d`). Both serve the widget and the chat on port 8080. Define one helper per shell, the first line on the
server only:

    cd /opt/demostore && . ./.deploy.env
    dc() { docker compose -f compose.yaml -f deploy/compose.server.yaml --profile shadow "$@"; }

On a laptop use this instead (the server file needs images that exist only there):

    dc() { docker compose --profile shadow "$@"; }

`.deploy.env` holds the commit that is running (`$SHA`) and the two image names. The jobs below are the same image with another
command: `dc run --rm -T jobs python <job>.py`. We never start, stop or change DemoStore's own systems (`sandbox/systems/`).

If the stack runs without the product compose (the chat service started on its own on port 8000, the widget on 5173), use
port 8000 in every `curl` below; the `dc` commands need the compose and do not work there.

**What was checked, and what was not.** On 27 Oct 2026 the commands were run one by one from a laptop with the chat service on
port 8000. Worked: everything in entry 1 (the first check, the switch off and on, the read-back), the status-code check in entry 6
and `gh run list --limit 10` in entry 7. Every other command is marked **Not checked yet** in its entry: it needs Docker
(the session that checked could not use it), or it writes, restarts or deploys. Each is to be run on the server with Ravi Menon's team at the handover
meeting; whoever runs one corrects the entry.

**Two workflows are switched off.** `gh workflow list --all --repo termidy/FDE-Bootcamp` showed `deploy` and `nightly` as
`disabled_manually` on 27 Oct 2026 (`checks` and `eval` are active). A disabled workflow starts nothing: `gh workflow run deploy`
is refused, and the 02:17 UTC nightly replay does not run, so it cannot turn red. `docs/teardown.md` step 0 is where `deploy` is
disabled; the repository does not say who disabled `nightly` or why. The same command lists them again:

    gh workflow list --all --repo termidy/FDE-Bootcamp

Enabling is a decision, not a step on the night:
- `deploy`: the **account owner** (who runs the teardown) decides, with the Director of E-commerce Engineering. Enable it only when
  the server is meant to be running. Once it is on, every merge to `main` deploys, and with the deploy role still in place a deploy
  starts a new server if the old one is gone; the teardown removes the server's containers, DemoStore's systems on it, the order
  store and all shadow rows (`docs/teardown.md`, step 2). Look first at whether the server exists (`docs/teardown.md`, step 3).
- `nightly`: the **Director of E-commerce Engineering** decides. It calls Claude every night with the repository's
  `ANTHROPIC_API_KEY` secret (about 0.40 USD a run, see entry 7), and a red run emails whoever last changed the schedule (gap 1).

The command, once the decision is made (the same line with the other name for the other workflow):

    gh workflow enable deploy --repo termidy/FDE-Bootcamp

To see it worked, the same `gh workflow list --all` shows it `active`. To read the last run of a switched-off workflow, name its
file, not its name: `gh run list --workflow deploy.yml --limit 1 --repo termidy/FDE-Bootcamp` works while `--workflow deploy`
answers "could not find any workflows named deploy".

The go-live page is `http://localhost:8080/golive`; the numbers behind it are `GET /api/golive`, the switch is
`GET` and `POST /api/golive/switch`. The pilot page (`/pilot`) is not an alert.

---

## 1. The go-live page shows "ALERT: the assistant gave a confidently wrong answer on the latest day"

**What it means.** On the latest day that has chats, more than 1 in 100 of the assistant's chats were marked confidently wrong
(the limit is `margins.confidently_wrong` = 0.01 in `sim_assumptions.json`; the check is `golive.wrong_line`). This is the first
signed rollback line. Customers in the assistant's group (the share and the live questions are in
`GET /api/golive/switch`; at launch 5 % of visitors and order status only) are getting a status or
a date stated as fact that is wrong. The banner reads the latest day only; it never clears on its own while no new chats arrive.

**First check.** Open `http://localhost:8080/golive` and read the table "Latest day (the alert)": the `detail` column says "N of M
assistant chats". The same from a terminal:

    curl -s http://localhost:8080/api/golive | python3 -c "import json,sys; print(json.load(sys.stdin)['lines']['day'])"

Then rule out the cause found in the drill: no carrier file. Run entry 2's first check; if the newest file is not
today's after 03:00 UTC, that is the cause.

**How to act.** Switch the assistant off. On the page, press "Switch the assistant off". The same call from a terminal:

    curl -s -X POST -H 'Content-Type: application/json' -d '{"on": false}' http://localhost:8080/api/golive/switch

New chats go to a person at once, with no deploy; a chat already open goes to a person on its next message, with everything said
so far (`app.py`, `_route`). If ServiceNow cannot take the case, the customer is told nothing was passed on (`handoff.DOWN_REPLY`).
Switching back on is not yours alone: the three lines were signed by the Chief Digital Officer, the Head of Customer Support and
the Finance and Returns Controller; the engineer who owns the fix brings them the proof (the labeled conversations replayed with
`python replay.py --gate`, and the bad day's chats) and they decide. To switch on, use the page's "Switch the assistant on".

**How to see it worked.**

    curl -s http://localhost:8080/api/golive/switch

shows `"on": false`; on the page the row "Assistant" shows OFF, with the note "The assistant is now off (the service answered in N s)". The
red banner stays until a day with chats comes in clean, which is expected.

**Not checked yet.** The page itself: that the row "Assistant" shows OFF with the note "The assistant is now off (the service
answered in N s)", and the "Switch the assistant on" button. Only the `curl` calls were run. To run on the server with Ravi Menon's
team at the handover meeting.

**Who next.** Tell the Head of Customer Support (chats now go to the live queue in ServiceNow). The fix is the Director of
E-commerce Engineering's.

---

## 2. `pipeline stopped, nothing written: …` (the hourly order load)

**What it means.** The load did not happen and nothing was written; the order store keeps the last good data. The message names
the check: `row count` (a run outside 25 % of the median of the last runs), `parcels known`, `statuses`, `news fresh` (newest news
over 30 hours old), `file arrived` (after 03:00 UTC the newest carrier file is not today's: `carrier: file carrier-YYYY-MM-DD.csv
is missing`), or the source that could not be read. An Oracle, SFTP or PostgreSQL error is not caught and ends in a traceback
instead (`docs/quick-fixes.md`, the row on `main()`), still with a non-zero exit.
**Customers feel:** nothing until 03:00 UTC. After 03:00 UTC, yesterday's carrier news counts as old (`tools._stale`): for every
parcel not delivered, the tools drop the news date and the promised date and flag the parcel, and the assistant is told to offer a
person (the wording is the prompt's). Delivered parcels are unaffected.

**First check.** The files on the carrier's server and the time of the last good load:

    dc run --rm -T jobs python -c $'import carrier\nwith carrier.connect() as f:\n    print(sorted(f.names()))'
    dc run --rm -T jobs python -c "import store; print(store.Store().watermark())"

The first lists `carrier-YYYY-MM-DD.csv` names only. The second prints the finish time of the last good load.

**How to act.** The carrier's file is not ours to make. If the newest name is older than today's date (UTC) and it is past 03:00
UTC, the carrier did not deliver: tell the Director of E-commerce Engineering. When the file is on the server, load again; a
second run on the same data leaves the store the same, and a failed run writes nothing:

    dc run --rm -T jobs python pipeline.py

For `row count`, `parcels known` or `statuses`: the message names the figures or the order; the data in Ledgerline changed shape
(a sale, a new status code). That is for the database administrator who owns Ledgerline and the engineer; do not loosen a check
on the night. Do not run two loads at once (there is no lock yet).

**How to see it worked.** The run prints `pipeline ok: N orders, N parcels` and `echo $?` gives `0`; the `watermark()` command
above now shows a time from the last minutes.

**Not checked yet.** Every `dc run --rm -T jobs python …` command in this entry: the two first checks (the carrier's file names and
`watermark()`) and `pipeline.py` (a write: it loads the order store). The messages the entry quotes are tested against the code, not
against a real run. To run on the server with Ravi Menon's team at the handover meeting.

**Who next.** The Director of E-commerce Engineering (carrier feed); the database administrator (Ledgerline unreachable or
changed).

---

## 3. `RETURN WINDOW DIFFERS - …` (code and policy pages disagree)

**What it means.** `returns.WINDOWS` and `returns.US_OPENED` (14 days for UK, DE, FR, IT; 30 days for the US, 15 if opened) do
not match the "Return window" section that is valid today in Confluence (space `POL`). The message names the market and both
numbers. The job exits non-zero. **Customers feel:** a customer can be told one window by a policy answer (from the page) and
judged by another when a return is decided (`returns.decide`, from code). While only order-status questions are live, the
assistant's group does not reach return decisions; the live intents are in the `intents` field of
`curl -s http://localhost:8080/api/golive/switch`.

**First check.** Read-only, no rebuild:

    dc run --rm -T jobs python policy_index.py --check

**How to act.** Which side is right is not an engineer's decision: it is the rule's owner (see Owners). When the page is right,
the engineer changes `WINDOWS` or `US_OPENED` in `returns.py` through a pull request; the fast tests and the replay must pass, then
merge to `main` deploys it. When the code is right, the page owner corrects the page, and the next hourly `python policy_index.py`
rebuilds the index, or run it now:

    dc run --rm -T jobs python policy_index.py

**How to see it worked.** `dc run --rm -T jobs python policy_index.py --check` prints `return windows: code and pages agree` and
exits `0`.

**Not checked yet.** `policy_index.py --check` (read-only) and `policy_index.py` (a write: it replaces the index), both through `dc run
--rm -T jobs`. To run on the server with Ravi Menon's team at the handover meeting.

**Who next.** The Head of Customer Support (the return rules); the Finance and Returns Controller when the change touches
refunds.

---

## 4. `policy index not rebuilt: …`

**What it means.** The rebuild stopped; the old index stays (the replacement is one transaction, `policy_index.Index.replace`).
The message gives the cause: Confluence unreachable, a page with no market or no valid-from (`page N ('Title') has no market`),
a duplicate heading (`page N has the heading 'X' twice`), no sections at all (`Confluence gave no sections; the index is not
replaced`), or a database error. One bad page stops the whole rebuild (`docs/quick-fixes.md`). **Customers feel:** policy answers
come from the last good index, so a page edit does not show; sections are still chosen by the date they are valid.

**First check.** Run it once and read the message:

    dc run --rm -T jobs python policy_index.py

**How to act.** The message names the page and the fault. The page owner fixes that page in Confluence; then run the same
command again. For "Confluence unreachable" or a database error, the cause is outside the page: tell the Director of
E-commerce Engineering.

**How to see it worked.** The run prints `N sections stored; per market before {...}, after {...}` and then `return windows: code
and pages agree`, and exits `0`.

**Not checked yet.** `dc run --rm -T jobs python policy_index.py`, the first check, which is also a write (it replaces the index
when it succeeds). To run on the server with Ravi Menon's team at the handover meeting.

**Who next.** The page owner (Head of Customer Support's team); the Director of E-commerce Engineering for Confluence or the
database.

---

## 5. `the assistant failed; the chat goes to a person` (in the chat container's log)

**First, is `deploy` on?** The redeploy below needs it, and on 27 Oct 2026 it was `disabled_manually`. Check with
`gh workflow list --all --repo termidy/FDE-Bootcamp`. To enable it: `gh workflow enable deploy --repo termidy/FDE-Bootcamp`, but
the account owner decides, with the Director of E-commerce Engineering, and only when the server is meant to be running (see
"Two workflows are switched off" in "Before you start"). Not checked yet: the enable command. To run on the server with Ravi
Menon's team at the handover meeting.

**What it means.** Something on the assistant's path raised (for example a model call that is refused, out of credit or timed out). The
chat is handed to a person with everything said so far and the customer is told so; this is a log line, not a banner. The page's
rows do not record the cause: the row just says the chat was handed off. If it happens on every chat of the assistant's group,
that group is effectively not served, and nothing else tells you.

**First check.** How many in the last hour, and the cause (the last line of the traceback names the error):

    dc logs --since 1h chat 2>&1 | grep -c 'the assistant failed'
    dc logs --since 1h chat 2>&1 | grep -A 30 'the assistant failed' | tail -40

**How to act.** One now and then: nothing. Several in a row: switch the assistant off (entry 1) so that chats stop trying and go
to a person at once, then fix the cause. If the traceback names the key or the credit, the key is read from the SSM parameter
`/fde-course/anthropic-api-key` at deploy time (`deploy/remote-deploy.sh`, step 4): the account owner corrects the parameter or the
credit in the Claude Console, then redeploys the commit that is running:

    echo $SHA
    gh workflow run deploy --ref main -f commit=$SHA --repo termidy/FDE-Bootcamp

The deploy ends with one real chat and is red when it fails. If the redeploy recreates the chat container, open chats lose their
history (sessions live in memory, `docs/quick-fixes.md`).

**Not checked yet.** The redeploy step (and whether it recreates the container after only the key changed) was not run: we cannot run a
deploy here. The on-call engineer in E-commerce Engineering checks it on the first real redeploy during the two weeks we are still
backup, and corrects this entry. Also not run: both `dc logs … | grep` first checks, `echo $SHA` (it needs the server's
`.deploy.env`) and the `dc logs --since 10m` count. To run on the server with Ravi Menon's team at the handover meeting.

**How to see it worked.** After ten minutes with the assistant on:

    dc logs --since 10m chat 2>&1 | grep -c 'the assistant failed'

prints `0`, and `gh run list --workflow deploy.yml --limit 1 --repo termidy/FDE-Bootcamp` shows `completed success` (name the file:
while `deploy` is disabled, `--workflow deploy` is refused).

**Who next.** The Director of E-commerce Engineering; the account owner of the Anthropic key.

---

## 6. A container is unhealthy: `chat` or `shadow`

**First, is `deploy` on?** Only the rollback at the end of the `chat` part needs it, and on 27 Oct 2026 it was `disabled_manually`.
To enable it: `gh workflow enable deploy --repo termidy/FDE-Bootcamp`, decided by the account owner with the Director of
E-commerce Engineering (see "Two workflows are switched off" in "Before you start"). If the server is the thing that is gone, a
rollback is not a rollback: it would start a new server. Not checked yet: the enable command. To run on the server with Ravi
Menon's team at the handover meeting.

**First check, for both.**

    dc ps

**`chat` is `unhealthy` or missing.** The health check fetches `/openapi.json` and has failed for about a minute (`compose.yaml`).
**Customers feel:** the widget answers "Something went wrong. Please ask for a person." (`widget/src/App.tsx`) and nothing passes
the chat to a person. The go-live page's numbers and the switch come from the same service, so the page cannot load them; the
switch is not needed, nothing is answering.

    dc logs --tail 100 chat
    dc restart chat

A restart loses every open chat's history (sessions are in memory). Wait two minutes, then `dc ps` must show `chat running
healthy` and

    curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/golive/switch

must print `200`. If it is not healthy again, roll back to the last green deploy:

    gh run list --workflow deploy --limit 5 --json conclusion,headSha,createdAt --repo termidy/FDE-Bootcamp
    gh workflow run deploy --ref main -f commit=<a headSha with conclusion success, before the current one> --repo termidy/FDE-Bootcamp

A rollback works only for a commit whose images are already built (`.github/workflows/deploy.yml`, input `commit`).

**`shadow` is `unhealthy`.** Its heartbeat file is older than 90 seconds. **Customers feel:** nothing; shadow mode answers on the
side. The pilot page falls behind; when it runs again it reads every chat opened after the newest one stored. Each tick prints
`stored N, closed N, errors N, clashes N`:

    dc logs --tail 50 shadow
    dc logs --since 1h shadow 2>&1 | grep -E 'errors [1-9]|clashes [1-9]'
    dc restart shadow

The second line matters because the heartbeat is also written after a tick with errors, so `healthy` does not mean no errors.
After a restart `dc ps` shows `shadow running healthy` within two minutes and the log shows a new tick line.

**Not checked yet.** `dc ps`, `dc logs`, both `dc restart` commands (restarts), and the two rollback commands (`gh run list --workflow
deploy --limit 5 --json …`, then `gh workflow run deploy …`, a deploy). Only the status-code `curl` was run, against the chat service
on port 8000, and it printed `200`. To run on the server with Ravi Menon's team at the handover meeting.

**Who next.** The Director of E-commerce Engineering. The Head of Customer Support only needs to hear about `chat`.

---

## 7. A red check in GitHub: `checks`, `nightly` or `deploy`

**First, are `nightly` and `deploy` on?** On 27 Oct 2026 both were `disabled_manually`, so neither can turn red: no red `nightly`
means nothing while it is off, not that the model and the pages are fine. Check with
`gh workflow list --all --repo termidy/FDE-Bootcamp`. To enable: `gh workflow enable nightly --repo termidy/FDE-Bootcamp` and
`gh workflow enable deploy --repo termidy/FDE-Bootcamp`. Who decides: for `nightly`, the Director of E-commerce Engineering (it spends
the Anthropic key every night); for `deploy`, the account owner with the Director, only when the server is meant to be running (see
"Two workflows are switched off" in "Before you start"). Not checked yet: the two enable commands. To run on the server with Ravi
Menon's team at the handover meeting.

**What it means.** Three different things, and the first line of the run says which.
- `checks` on a pull request: a change with a red check must not be merged; `main` is untouched and customers feel nothing.
- `nightly` (02:17 UTC), the replay of the 40 conversations and the 10 hard messages, red on a day when nobody pushed: the model or
  a policy page changed. Customers feel nothing yet; the assistant that is live may now behave differently.
- `deploy` after a merge to `main`: the server may be on the previous commit or half-updated. `deploy/check.sh` prints `NOT UP:`,
  `chat: HTTP <code>`, or `check failed: empty reply` / `no source link in the reply`.

**First check.**

    gh run list --limit 10 --repo termidy/FDE-Bootcamp
    gh run view <run-id> --log-failed --repo termidy/FDE-Bootcamp

For `eval / replay` the run's summary page lists each `MISS` with the conversation id, then `GATE: fail` and the reasons. The gate
is at least 36 of 40 right; one or two misses either way are normal for the model.

**How to act.**
- `checks`: fix on the branch and push; do not re-run for a green you do not understand.
- `nightly`: run the same replay and the policy check yourself, with the key in `.env` and DemoStore's systems up (about 0.40 USD),
  and compare with the last green night:

      python replay.py --gate
      python policy_index.py --check
      gh run list --workflow nightly --limit 5 --repo termidy/FDE-Bootcamp

  Below 36, or a hard message failing any of its 3 runs, is a real change: a prompt or a page owner is next, not a re-run. If the
  go-live page also shows the alert, go to entry 1.
- `deploy`: if the cause is not clear from the log in a few minutes, roll back as in entry 6.

**How to see it worked.** `gh run list --workflow nightly.yml --limit 1 --repo termidy/FDE-Bootcamp` (or `--workflow deploy.yml`)
shows `completed success`; a deploy log ends with `check ok`. Name the file: while a workflow is disabled, `--workflow nightly`
is refused ("could not find any workflows named nightly"); the file name still finds its last run.

**Not checked yet.** `gh run view <run-id> --log-failed` (every run in the list was green, so there was no failed run to read),
the `nightly` commands `python replay.py --gate`, `python policy_index.py --check` and `gh run list --workflow nightly --limit 5`
(the replay spends about 0.40 USD and needs DemoStore's systems and the key), the `eval / replay` summary page, and a `deploy`
log ending in `check ok`. Worked: `gh run list --limit 10 --repo termidy/FDE-Bootcamp` and, with the file name, `gh run list
--workflow deploy.yml --limit 1` and `--workflow nightly.yml --limit 1`. To run on the server with Ravi Menon's team at the handover
meeting.

**Who next.** The Director of E-commerce Engineering's team (the change); the Head of Customer Support when the cause is a policy
page.

---

## Gaps

Things that should raise an alert and do not, or that nobody has written down. None is an entry above because there is nothing
to act on when it happens. Each has an owner by role, proposed.

| # | Gap | Evidence | Owner (proposed) |
|---|---|---|---|
| 1 | **Nothing sends a message.** Cron output, container health and CI email do not reach the person on call, the alert on the go-live page shows only while the page is open, and GitHub's email goes to the person who last changed the schedule, which is us. To do before we leave. | `README.md` (the hourly pipeline, "GitHub emails the person who last changed the schedule"); `compose.yaml` health checks; `widget/src/GoLive.tsx:216` | Director of E-commerce Engineering |
| 2 | **A job that never starts is invisible.** The cron lines are DemoStore IT's to install and are not in this repository; the deploy runs the jobs once. `retention.py` has no failure exit, and its first real run has not happened. | `README.md` (the cron lines, "IT's cron runs them"); `deploy/remote-deploy.sh` step 5; `retention.py` (no exit code); `docs/quick-fixes.md` (the retention row) | DemoStore IT (owner of the cron) |
| 3 | **Access is not written down.** The server has no SSH and no public address, so the page and the switch are reached from the server itself; how the on-call engineer gets a shell, and who holds the AWS account, the SSM parameter, the Anthropic Console and the GitHub repository, is not in this repository. | `README.md` (pilot page address); `.github/workflows/deploy.yml` header; `docs/teardown.md` ("the account owner") | Director of E-commerce Engineering |
| 4 | **A late or partial carrier file is seen by one signal only,** the hourly load, and only after 03:00 UTC. A parcel missing from the newest file has its stored news overwritten with nothing; only the newest file is read; the 03:00 UTC hour is a working value that DemoStore has not confirmed. | `checks.py` (`FILE_EXPECTED_BY`, `check_file_arrived`); `docs/quick-fixes.md` (rows on `newest_rows` and `UPSERT_PARCEL`); `docs/requirements.md` OQ-5 | Director of E-commerce Engineering |
| 5 | **Model, key or credit trouble has no signal and no count.** One log line per failed chat; the row does not keep the reason; the only other check is `doctor.py`, run by hand. | `app.py:203`; `app.py` (`_to_person`, `_record`); `doctor.py` | On-call engineer |
| 6 | **The go-live numbers can be wrong or off without a sign.** Failed writes of go-live rows are counted in `record_failures` and never read; if the settings cannot be read the assistant is off with no message; a failed table creation is one log line. | `app.py:154`, `:239` (`record_failures`); `app.py:160-166` (`live_settings`); `app.py:40` | On-call engineer |
| 7 | **Health checks say less than they seem to.** `chat` is healthy while the database, Claude, Confluence or the carrier are down; `shadow` is healthy after ticks with errors; chat sessions are never purged, so memory grows until a restart. | `compose.yaml:19-24`, `:45-50`; `shadow.py:447-451` (the heartbeat is written after every tick); `docs/quick-fixes.md` (the `SESSIONS` row) | On-call engineer |
| 8 | **The page's banner covers one line, and nobody is required to read it.** The other signed lines (hand-off, unanswered, rating) show "does not hold" in a table with no banner. | `golive.py:441-442`; `widget/src/GoLive.tsx:120`, `:216` | Support shift lead on the morning shift |
| 9 | **A page edit that breaks the return rules is caught up to an hour later,** by the hourly index job only. | `docs/quick-fixes.md` (the row on `policy_index.py:223`); `policy_index.py:214-220` | Head of Customer Support |
| 10 | **Two workflows are off, so two alerts cannot happen.** `deploy` and `nightly` were `disabled_manually` on 27 Oct 2026. With `nightly` off nothing replays the 40 conversations on a day nobody pushes, and the rollback and redeploy in entries 5 and 6 are refused. Nobody has decided whether they come back on. | `gh workflow list --all`; `docs/teardown.md` (step 0, `deploy`); `.github/workflows/nightly.yml` | `deploy`: account owner; `nightly`: Director of E-commerce Engineering |

---

## Owners after we leave

These are roles at DemoStore, taken from what the repository records. **All are proposed.** Nobody at DemoStore has agreed to them
yet: each is to be confirmed with the Director of E-commerce Engineering and the Head of Customer Support at the handover meeting,
and a "no" goes into this table.

| Question | Role (proposed) | What the repository says |
|---|---|---|
| Who changes the prompts? (`agent.py` `SYSTEM`, `intent.py` `PROMPT`) | An engineer in E-commerce Engineering, reviewed by a second engineer; the Director of E-commerce Engineering is accountable. | The Director asked for the code to be reviewed by his team (`docs/problem-statement.md`, `docs/requirements.md` OQ-18). A prompt change must pass the replay gate: 36 of 40, and the 10 hard messages 3 of 3 (`.github/workflows/eval.yml`, `.github/workflows/nightly.yml`). |
| Who adds labeled conversations to the evals? | The Head of Customer Support decides the label (the right action, whether a person is needed); an engineer in E-commerce Engineering adds the entry. | `data/conversations.json` has `action` and `needs_human` per conversation. The repository does not say who labeled the first 40. `data/held_out.json` stays closed (`docs/plan.md`). |
| Who approves a change to the return rules in Confluence? | The Head of Customer Support for the rule; the Finance and Returns Controller as well when it touches refunds or amounts. | OQ-6 (which return rules are correct) and OQ-1 (the refund threshold) in `docs/requirements.md`. A changed window also needs the same change in `returns.py` (entry 3). |
| Who confirms the hour the carrier's file is due? | The Director of E-commerce Engineering. | `checks.FILE_EXPECTED_BY` is 03:00 UTC, "a working value" until his team confirms it (`docs/requirements.md` OQ-5; `docs/drill-notes.md`). That OQ row also names the database administrator, who owns Ledgerline; the file is the carrier's, so this table picks the Director. **Open today.** |
| Who reads the go-live page each morning? | A support shift lead on the morning shift, who reports to the Head of Customer Support. | `docs/brief-handover.md`: the shift leads may ask the on-call engineer to use the kill switch. The page's alert is only read when opened (gap 8). |
| Who owns the kill switch? | The on-call engineer in E-commerce Engineering, at the request of a support shift lead or on their own reading of the page. | `docs/brief-handover.md`: the on-call engineer owns the kill switch. Switching back on: the three who signed the rollback lines (entry 1). |
| Who owns the alerts and this runbook? | The Director of E-commerce Engineering. | The first gap above. |
