# DemoStore support assistant

The project of the Forward Deployed Engineer Bootcamp: a support and sales chat for DemoStore, built at the client,
step by step. Each day of the course starts from a tag, so you can always catch up:

    git checkout c1-d4-start

Put your Claude API key into `.env` (copy `.env.example`). Never commit `.env`.

New to the course? Start with [For learners](#for-learners) at the end of this file.

## The hourly pipeline

`python pipeline.py` reads Ledgerline and the carrier's newest file, runs the four checks and, only if all pass, loads the
order store in one transaction. A failed check writes nothing, keeps the last good data and exits non-zero with the check's
name on stderr. The scheduler is Ravi's team's to install; the line to give them:

    0 * * * * cd /path/to/repo && python pipeline.py


### Run it again after a failure

A failed run writes nothing and keeps the last good data, so it is safe to run again at any time:

    python pipeline.py

Read the message on stderr: it names the check (`row count`, `parcels known`, `statuses`, `news fresh`) or the source that
could not be read. Fix the cause (for example, wait for the carrier's new file) and run the same command; two runs on the
same data leave the store identical. Do not start two runs at the same time (there is no lock yet, see
`docs/quick-fixes.md`).

### Checks

Fast tests, no network: `python -m pytest -q -m "not live"`.

The live check, against the real copy of Ledgerline, the SFTP server and PostgreSQL (run it on purpose, not by habit):

    python -m pytest -m live test_pipeline_live.py

It runs the pipeline twice and compares the store. `python probe_live.py` only looks at the three systems and writes nothing.
The 40 labeled conversations: `python replay.py`.

## The return flow

A verified customer asks to return an item. `prepare_return` (a model tool) reads the order's lines from Ledgerline
(read-only), applies the return rule and `money.py`, and keeps an offer in the session. Only the customer's own "yes"
(`/chat` checks it before the model runs) writes the draft: one row with status `W` in `LL_RTN_REQ_STG` through the writer
account, then one approval task in ServiceNow. A person approves; no code moves money. Damage on arrival, a request for a
person, anger, anything not covered, and two failed tries open a hand-off case in ServiceNow instead.

### The live check of the return flow (it writes)

    python -m pytest -s -m live test_returns_live.py

This one **writes**: one draft with a `TEST-` key into the real `LL_RTN_REQ_STG` and one real task in ServiceNow, read back
and then repeated to check that nothing new appears. It creates no hand-off case. The rows cannot be deleted by us; Ravi's
team clears the `TEST-` rows, so run it on purpose, not by habit. Other live tests that call Claude, such as
`python -m pytest -m live test_damaged_live.py`, write only to fakes.

## The policy answers (Build 4)

The assistant answers questions about returns, warranty and delivery rules from the policy pages in Confluence (space `POL`,
read only), never from memory. The pages are cut into sections, embedded locally (`fastembed`, no text leaves the machine) and
stored in our PostgreSQL (`policy_sections`, needs the `vector` extension). Only sections of the customer's market that are valid
today are searched; with no page close enough the assistant offers a person. The market comes from the verified customer's order,
else from the `market` the site sends to `/chat`, else from what the customer says; with none it asks.

Which command is which:

| Command | What it does | When |
|---|---|---|
| `python policy_index.py` | reads `POL`, rebuilds the index in one transaction, then checks that `returns.py` and the "Return window" pages agree; exits non-zero on a difference | hourly: `0 * * * * cd /path/to/repo && python policy_index.py` |
| `python policy_index.py --check` | only the code-versus-pages check, no rebuild | after a page edit, on demand |
| `python retention.py` | deletes traces older than 90 days | daily: `0 3 * * * cd /path/to/repo && python retention.py` |
| `python replay.py` | the 40 labeled conversations, scored; policy chats are scored on the page link of `data/policy_key.json`; calls Claude, writes only to fakes | on demand |
| `python probe_live.py build4` | read-only look at Confluence and PostgreSQL | on demand |

Run the index job once before the first chat, and again after any page edit (or wait for the hourly run). Two runs on the same pages leave the same index.
Before the first real `python retention.py`, dump the table: `pg_dump -t traces > traces-backup.sql` (outside git).

**Card numbers** are masked in the message before anything else sees it, in the reply, and so in the history, the traces and the cases.
**Every model call** is recorded in `traces` (prompt and reply after masking, tokens, cost). A trace that cannot be written does not block the reply:
it is counted in `traces.failures`, so "every call" has a counted gap.

**Erasure:** `POST /erase/start` with an email sends a code, as verification does; `POST /erase/check` with the code deletes that customer's traces
(found by an HMAC of the email, `TRACE_HMAC_KEY` in `.env`, and by her session ids), drops her in-memory chats and logs only the count of rows.
ServiceNow cases are **not** covered yet (open question OQ-S4-1); the reply says so.

The live checks of Build 4 (run on purpose; they call Claude or PostgreSQL):

    python -m pytest -m live test_retention_live.py          # traces, purge, erasure; temporary tables only
    python -m pytest -m live test_hard_messages_live.py      # the 10 hard messages, 3 runs, real Claude, fakes under it
    python policy_index.py                                   # the index live check: run twice, the counts must match

## Run in containers

One image for the Python code (the chat service and the jobs) and one for the widget (built with Node, served by nginx).
Nothing secret and no data is in an image: keys, passwords and addresses come from `.env` and `.env.containers` when a
container starts, and the order store, the traces and the policy index stay in our PostgreSQL.

    cp .env.containers.example .env.containers      # the hosts as containers see them; put the PostgreSQL password into STORE_URL
    docker compose up -d --build                    # the chat service and the widget: http://localhost:8080
    docker compose run --rm jobs python policy_index.py --check   # a job: do the code and the pages agree?

DemoStore's systems run in their own compose project (`systems`); our containers join its network `systems_default` and reach
them by service name. ServiceNow and Confluence run on this machine and are reached through `host.docker.internal`. We never
start or stop the `systems` containers; `docker compose down` here stops only the chat service and the widget.

The jobs are the same image with another command. IT's cron runs them (`-T`: cron has no terminal):

    0 * * * *  cd /path/to/repo && docker compose run --rm -T jobs python pipeline.py
    5 * * * *  cd /path/to/repo && docker compose run --rm -T jobs python policy_index.py
    30 2 * * * cd /path/to/repo && docker compose run --rm -T jobs python retention.py

Not in the image: `.env`, the tests, the labs (`sandbox/`), `data/*.jsonl`, the dev tools. The embedding model is in the image,
so no start downloads it. A second `up` after a change rebuilds only what changed. The one-time codes of `/verify` and `/erase`
are written to a file inside the chat container (see `docs/quick-fixes.md`).

## Deploy

A merge to `main` runs `.github/workflows/deploy.yml`. It builds both images and tags them with the commit, pushes them to
Amazon ECR, makes sure the one server runs (an EC2 instance tagged `project=fde-course`, found, started or created), and on the
server starts DemoStore's systems and then our services with the images of that commit. The last step sends one real chat
through the widget and checks that the shadow worker runs; the workflow is red when that fails. GitHub gets into AWS without a
key (OpenID Connect, only for `main`); the Anthropic key is read from SSM on the server and is never in an image, in GitHub or
in a log. No port is open to the internet and there is no SSH: commands go through SSM.

- **Rollback:** Actions, `deploy`, Run workflow, `commit` = the full sha of an older commit. The images are not rebuilt; they
  must already be in ECR (the pull fails with the tag name if not). Rolling forward is the same with a newer sha.
- **Shadow report:** Run workflow with `report` ticked prints the 20 newest shadow chats (the customer's message, the assistant's
  action and answer, the agent's reply). In shadow mode the assistant answers every new live chat and nobody sees the answer.
- **Cost:** the server runs only while we work on it, a few cents an hour. A person ends it: [`docs/teardown.md`](docs/teardown.md) lists the
  commands in order and what each removes.

## Pilot page

Shadow mode answers every new live chat into `shadow_chats`; the pilot page is where Lena and Marco read the result.

- **Address:** `/pilot` on the widget. Locally `http://localhost:5173/pilot`; on the server port 8080, reached from the server
  itself (there is no public address yet).
- **What it shows:** the totals split by intent, market and action (every table adds up to one total; chats without an intent
  or tokens are listed as "unclassified" / "unpriced", never dropped), the cost per chat, three plain sentences (where we are
  against the 50% goal, what it costs, how sure we are), and a sample of chats to mark: same, better, worse or wrong (and
  whether a wrong answer sounded sure). The numbers come from code and SQL; the page makes no model call.
- **Who may open it:** anyone on DemoStore's internal network. There is no login; the name typed on the page is stored with each
  mark but is not checked. Customer emails never reach the page and card numbers are masked.
- **Retention:** the daily `python retention.py` also deletes `shadow_chats` older than 90 days and the marks of those chats.
  Before the first real run take a `pg_dump` of the `product` database.

## Checks on every pull request

Every change reaches `main` through a pull request, and GitHub runs the checks itself (`.github/workflows/`). A hook skipped on
a laptop does not skip them.

| When | Check | What it does | Time | Cost |
|---|---|---|---|---|
| every pull request | `python` | ruff, mypy and the fast tests (`-m "not live"`); no key, no network | about 1 min | none |
| every pull request | `widget` | `npm ci` and `tsc` in `widget/` | about 15 s | none |
| every pull request, after the two above are green | `eval / replay` | starts DemoStore's systems on the runner, loads the order store and the policy index, replays the 40 conversations with real Claude (`python replay.py --gate`) | about 1.5 min | about 0.40 USD |
| every night, 02:17 UTC | `nightly` | the same replay, and the 10 hard messages (3 runs each, all 3 of 3 must pass) | about 4 min in all: replay 2 min, hard messages 4 min, side by side | replay about 0.40 USD; hard messages under about 1 USD (estimated, see below) |

The times are from the first runs on GitHub (the first nightly: replay 38 of 40, hard messages 60 passed in 206 s). The replay's cost is
its tokens times the prices in `llm.py` (79 calls, 0.38 USD). The hard messages' cost is not measured, because that job prints no
token usage; the estimate is 60 tests with a few calls each at the replay's price per call. A new push to a pull request replaces the run still going;
a branch with no pull request runs nothing.

**The eval passes only at our goal:** at least 36 of the 40 right actions, no conversation that needs a person staying with the
assistant, and no draft written (the replay writes nothing: drafts, tasks and traces go to fakes). On a runner the clock is pinned
to `2026-10-22T05:00Z` (`DEMOSTORE_NOW`), because the sandbox's carrier files are from that week; with it unset the code reads the
wall clock. The key `ANTHROPIC_API_KEY` is a repository secret handed to the one step that calls Claude, so it is never in a log,
and a pull request from a fork gets none: its eval fails at once and a maintainer runs it from a branch in this repository.

**When a check is red:**

1. Open the failed check on the pull request. For `eval / replay` the run's summary page lists the replay: every `MISS` with the
   conversation id, what was expected and what was taken, then `GATE: fail` and the reasons.
2. Run the same conversations on your machine: `python replay.py --gate` (needs the systems up; it costs about 0.40 USD). One or two
   misses either way is normal for the model; fewer than 36 is a real change. Read the missed conversations before touching a rule.
3. If the cause is your change, fix it on the branch and push; the run starts again. Do not re-run a red eval to get a green one
   until you know why it failed.
4. A red `python` or `widget` is the same command as on your laptop: `ruff check .`, `python -m pytest -q -m "not live"`,
   `cd widget && npx tsc -b`.
5. A red `nightly` with no push that day means the model or a policy page changed: run the same replay, compare with the last green
   night, and read the policy pages (`python policy_index.py --check`). GitHub emails the person who last changed the schedule.

## For learners

This repository has two parts. The root is the product: the support chat for DemoStore that Claude Code builds in the
build lessons, with a tag for every day. `sandbox/` is your lab folder, where you type the small programs of the labs
(see `sandbox/README.md`). Both use DemoStore's systems in `sandbox/systems/`.

### Setup

**Path A - GitHub Codespaces (nothing to install on your computer).** Open this repository on GitHub, then Code,
Codespaces, Create codespace. Before that, add your Claude API key as a Codespaces secret named `ANTHROPIC_API_KEY`
(GitHub Settings, Codespaces, Secrets) and give it access to this repository. The environment installs everything and
starts the systems; then run:

    python doctor.py

Codespaces is free for a number of core-hours a month on a personal account; this environment uses 2 cores (or 4 if you
choose a bigger machine, which uses the hours twice as fast). Stop the codespace when you take a break.

**Path B - your own computer.** You need Python 3.12 or newer, Node 22, Docker and git. Then:

    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt -r sandbox/requirements.txt
    (cd widget && npm ci)
    cp .env.example .env && cp sandbox/.env.example sandbox/.env      # then put your key into both
    docker compose -f sandbox/systems/compose.yaml up -d
    python doctor.py

In both paths, set a monthly spend limit for your API key in the Claude Console before the first lab.

### Catching up

- In the labs: `python sandbox/catchup.py <lesson>` puts the lab files where they are when that lesson starts.
- In the builds: open a day's starting point in its own folder, next to your work:

      git worktree add builds/day4 c1-d4-start

  Copy your `.env` into that folder and work there; your own branch and the sandbox stay as they are.

