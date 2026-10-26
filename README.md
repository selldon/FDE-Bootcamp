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

