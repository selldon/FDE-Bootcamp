# Deploy - plan

Builds `docs/brief-deploy.md` (Day 9: deploy on merge, rollback, shadow mode, shadow report, teardown) in nine small phases. Each phase
ends in a check. I cannot reach AWS from this laptop and Docker is denied to me, so:
- **offline checks** I run myself: the fast tests (`python -m pytest -q -m "not live"`), ruff, mypy, `bash -n`, YAML parsing, `actionlint`/`shellcheck` if installed;
- **laptop checks that touch your stand-ins** (Phase 3, the worker with python against ServiceNow on 8021) are written out as exact commands for you to run; I stop;
- **AWS checks** run in GitHub Actions on `main`. For each one the plan says what to look for in the run, and I stop. Every AWS fix costs a
  pull request and a merge, so everything that can be caught on the laptop is caught there first.
One phase at a time. Tick the boxes as tasks are done. One commit per phase, only when you ask (pre-commit runs, never skipped). Every change reaches
`main` through a pull request with green checks; the branch is `deploy`.

First action after approval: copy this text to `docs/plan-deploy.md` (plan mode lets me write only the plan file now), commit it (pre-commit runs), and **stop**. The phases are run one at a time, each when you say so.

## Where we start (read from the code)

- `compose.yaml` (project `demostore`): `chat` (image `demostore-app`), `widget` (nginx on 8080, `depends_on` chat healthy), `jobs` (profile). It needs
  `.env` and `.env.containers`, both gitignored, so a fresh server has neither. `.env.containers.example` points ServiceNow and Confluence at
  `host.docker.internal:8021/8041` (laptop only); on the server they are `servicenow:8020` and `confluence:8040` in the `systems` project.
- `sandbox/systems/compose.yaml` (project `systems`): Oracle (`gvenzl/oracle-free`, `--wait` takes minutes), SFTP, Mailpit, PostgreSQL (`ourdb`, databases
  `assistant`, `product`), and four stand-ins built from `./sims` with the sim code mounted at `/systems`. So the server needs the repo files, not only images.
  `servicenow` takes `SNOW_INCOMING_EVERY` (0 = off).
- ServiceNow stand-in (`sandbox/systems/servicenow/sim.py`): live chats are `GET /api/now/table/interaction` with the **reader** account (`fde_reader` / `reader`),
  supports `ORDERBYopened_at^opened_at>...` and `number=...`, rate-limited (429 + `Retry-After`). A new chat is `state=work_in_progress`, `opened_for` = the customer's
  email; when closed it is `closed_complete` and `transcript` ends with `\nAgent: <reply>`. The 60-odd historical chats are in the same table.
  `config.servicenow()` is the *tasks* account (`fde_tasks`); there is no reader setting yet.
- `replay.py` already runs the real `answer()` with `refunds.set_systems(None, FakeDrafts, FakeServiceNow)` and `traces.set_sink(FakeTraces)`: nothing is written.
- Workflows: `checks.yml` (pull request: python, widget, then `eval.yml`), `nightly.yml`. None deploys. `eval.yml` pins `DEMOSTORE_NOW=2026-10-22T05:00:00+00:00` and uses the
  sandbox test values (not secrets).
- The repo `termidy/FDE-Bootcamp` is **public**, so the server can `git clone` it over HTTPS with no credential.

## Decisions made with you (2026-10-26)

1. **Systems files reach the server by `git clone` at the pushed commit**, over SSM. Rollback checks out the older commit, so systems and images always match.
2. **Shadow mode reuses the replay's fakes** (`shadow.py`): the real writers are never wired in, so "nothing leaves our database" holds by construction. Traces of shadow
   calls go to `FakeTraces` too (no customer text in the real `traces` table). What the fakes recorded (draft, task, case) is stored next to the answer.
3. **Server settings:** committed `deploy/server.env` (service names as hosts, sandbox test values, reader account, pinned `DEMOSTORE_NOW`) and
   `deploy/compose.server.yaml` (images from ECR through `${APP_IMAGE}` / `${WIDGET_IMAGE}`, `env_file: server.env`). `ANTHROPIC_API_KEY` is read from SSM into the
   shell only for `docker compose up` and passed through as a bare name: never in an image, GitHub, a log or a file. `compose.yaml` keeps working on the laptop.
4. **Network:** the default VPC, its default security group and the default subnet in **us-east-1a**. The workflow checks the group and fails if any inbound rule is open to the
   internet (`0.0.0.0/0` or `::/0`) before it starts a server. AMI: newest Amazon Linux 2023 by `ec2 describe-images`; Docker, the compose plugin and git are installed by user-data.
5. **`DEMOSTORE_NOW` is pinned in `server.env`** (the value `eval.yml` uses), so `pipeline.py` accepts the sandbox carrier files and the server answers as CI measured. One line in
   `docs/quick-fixes.md`: the server's clock is frozen at 22 Oct.

My defaults (tell me if wrong):
- The worker is a service in `compose.yaml` under profile `shadow` (so a plain `docker compose up` on the laptop does not need the reader account); the server starts it with `--profile shadow`.
- **New** = opened after the worker's watermark. On the very first start the watermark is "now" (history is not answered); afterwards it is the newest `opened_at` stored. A chat is stored once, keyed by its number.
- The store is a new table `shadow_chats` in the `product` database, created by the worker itself (as `retention.py` does for `traces`). `shadow.py report` prints the last 20 rows.
- The report on the server runs through the same workflow: a manual start with `report: true` sends `docker compose exec shadow python shadow.py report` over SSM and prints it.
- The CLAUDE.md rule "never start, stop or change [the systems containers]" is about the laptop's copy. The brief asks the deploy to start the systems **on the server**; I read it that way.
- The ECR repositories, the role, the instance profile `fde-course-ec2` and the SSM parameter exist already (brief). If a call is refused, it is a person's job: I write the exact command and stop.
- Starting an instance with the instance profile normally needs `iam:PassRole`, which the brief's list does not name. If `run-instances` is refused for that, it is the first thing I report (Phase 6).

## Phase 1 - settings and the shadow store (offline)
- [x] Save this plan as `docs/plan-deploy.md`.
- [x] `config.servicenow_reader()` (`SERVICENOW_READER_USER`, `SERVICENOW_READER_PASSWORD`, same URL); add the two names to `.env.example` and `.env.containers.example`. I do not read or edit your `.env`.
- [x] `shadow.py`, store part: `ShadowStore` (PostgreSQL, `shadow_chats`: `number` primary key, `opened_at`, `opened_for`, `market`, `message`, `intent`, `action`, `answer`, `would_have` JSON, `state`, `agent_reply`, `answered_at`;
      `CREATE TABLE IF NOT EXISTS`), a fake store for tests, `watermark()`, `save()` (insert, never overwrite), `close(number, agent_reply)`, `last(n)`.
- [x] Tests (`test_shadow.py`): saves once per number; the watermark; `close` only fills an empty `agent_reply`; the table holds no other data than the chat.
- [x] Check (I run): fast tests, ruff, mypy pass.

## Phase 2 - the worker and the report (offline)
- [x] `shadow.py`, run part: `poll(client, store, answerer)` - read new chats with the reader account (`opened_at>watermark`, ordered, paged), for each run `answer()` as a verified `refunds.Context(opened_for, f"shadow-{number}", market=u_market)` with `FakeDrafts`, `FakeServiceNow`,
      `FakeTraces` set; store action, answer, and what the fakes recorded (`ctx.offer`, drafts, tasks, cases); then read stored rows still without a reply whose chat is `closed_complete` and store the text after `Agent:`.
      One bad chat or a ServiceNow error (429 with `Retry-After`, timeout, 5xx) is logged and retried next tick; it never stops the loop.
- [x] `python shadow.py` loops every `SHADOW_EVERY` seconds (default 30) and touches a heartbeat file each tick; `python shadow.py --once` does exactly one tick and exits (non-zero if the tick failed); `python shadow.py report` prints the last 20 rows (message, action, answer, agent reply).
- [x] Tests: a fake ServiceNow client with new, old and closed chats; **the real `servicenow.send`, `drafts.create` and the writer account are never called** (they are patched to raise); a verified `opened_for` reaches the order tools; 429 is retried; a chat answered twice is stored once; the report prints 20 rows.
- [x] `compose.yaml`: service `shadow` (same image and env as `chat`, `command: python shadow.py`, `restart: unless-stopped`, profile `shadow`, healthcheck = heartbeat younger than 90 s, no ports).
- [ ] Check (I run): fast tests, ruff, mypy, YAML parses, `shadow` shares `chat`'s image, no secret in the file.

## Phase 3 - the worker against the stand-in, on the laptop (python, no Docker; for you)
On this laptop the ServiceNow and Confluence stand-ins run outside Docker, on ports 8021 and 8041 (the values already in `.env`), so the worker runs with
python against them and the laptop's PostgreSQL. No container is started or changed.
- [x] **Check for you.** Add `SERVICENOW_READER_USER=fde_reader` and `SERVICENOW_READER_PASSWORD=reader` to your `.env` if they are not there; restart the ServiceNow stand-in
      with `SNOW_INCOMING_EVERY=10` (your command; it is the author's copy). Wait about 60 seconds for a few chats, then:
  ```
  python shadow.py --once                      # one tick: reads the new chats, answers them, stores them; prints how many
  python shadow.py report                      # rows with message, action, answer
  python shadow.py --once                      # a second tick: the same chats are not stored twice; a chat closed meanwhile gets the agent's reply
  python shadow.py report
  ```
  Look for: every row has an answer; the row count only grows by chats that are really new; no new task at `localhost:8021/tasks` and no new case at `/live`;
  the first tick of an empty table stores nothing from the history. Then restart the stand-in with `SNOW_INCOMING_EVERY=0`.
  **Stop.**
- Result (27.10): first tick on the empty table stored 0 (history skipped); the next ticks stored 35 and 62 new chats, 0 errors; all 97 rows have
  an answer and, once closed, the agent's reply; no task at /tasks, no chat at /live. Actions: 52 hand_off, 21 give_status, 13 reply, 11 start_return.
  The stand-in is back on `SNOW_INCOMING_EVERY=0`.

## Phase 4 - what runs on the server (offline)
- [ ] `deploy/server.env`: hosts by service name (`ledgerline`, `carrier:22`, `ourdb`, `servicenow:8020`, `confluence:8040`), the sandbox test values, the reader account, `DEMOSTORE_NOW=2026-10-22T05:00:00+00:00`, `TRACE_HMAC_KEY` (a test value, labelled), no key.
- [ ] `deploy/compose.server.yaml`: overrides `chat`/`shadow`/`jobs` to `image: ${APP_IMAGE}` (no build), `widget` to `${WIDGET_IMAGE}`, `env_file: [deploy/server.env]`, `environment: [ANTHROPIC_API_KEY]`.
- [ ] `deploy/remote-deploy.sh <sha>` (runs on the server as root through SSM): `git clone` / `fetch` and `checkout <sha>`; `SNOW_INCOMING_EVERY=120 docker compose -f sandbox/systems/compose.yaml up -d --wait`; wait for PostgreSQL's "init process complete";
      ECR login (instance role); read `/fde-course/anthropic-api-key` into a shell variable (never echoed, `set +x`); `docker compose ... pull`; `jobs pipeline.py`, `policy_index.py`, `retention.py` (create tables; idempotent upserts); `up -d --profile shadow`.
- [ ] `deploy/check.sh`: `curl` one real chat to `localhost:8080/chat` (a policy question: the reply has the source link, and a non-200 or an empty reply fails), `docker compose ps` shows `chat`, `widget`, `shadow` healthy; prints the commit and the image tags that run.
- [ ] `docs/quick-fixes.md`: frozen clock; test passwords on the server; the key is read at start (rotation needs a redeploy); no HTTPS and no public port until day 11; sessions in memory are lost at each deploy.
- [ ] Check (I run): `bash -n`, `shellcheck` if present, YAML parses, `grep` finds no key or password that is not a labelled test value, no `set -x` near the key, fast tests pass.

## Phase 5 - `.github/workflows/deploy.yml` (offline)
- [ ] Triggers: `push` to `main`; `workflow_dispatch` with `commit` (rollback, default the current head) and `report` (boolean). `permissions: id-token: write, contents: read`. No GitHub environment. `concurrency: deploy` without cancel (a deploy is never cut short).
- [ ] Job `images` (skipped on rollback and on report): OIDC with `vars.AWS_DEPLOY_ROLE_ARN`, region `us-east-1`; ECR login; build `fde-course/demostore-app:<sha>` and `fde-course/demostore-widget:<sha>`, push; print the digests.
- [ ] Job `server`: **security-group guard** (`describe-security-groups` on the default group: fail on any inbound rule from `0.0.0.0/0` or `::/0`); find the instance with tag `project=fde-course` not terminated; start it if stopped, else `describe-images` (newest AL2023) + `run-instances`
      (`t3.large`, 30 GB gp3, tags on instance and disk, default subnet in us-east-1a, instance profile `fde-course-ec2`, user-data installs Docker, compose plugin, git); wait for the SSM agent to be online; print instance id, type, state, disk size.
- [ ] Job `deploy`: `ssm send-command` (`AWS-RunShellScript`) running `remote-deploy.sh <sha>` then `check.sh`; wait; print the output; **red** on any non-zero exit. With `report: true` it runs only `docker compose exec shadow python shadow.py report`.
- [ ] Actions pinned by version like the others; no secret anywhere (only the repository variable). The workflow never prints the key (the script reads it on the server).
- [ ] Check (I run): YAML parses, `actionlint` if present, fast tests pass; `grep` shows no `secrets.` in the file and no ARN. Open the pull request; `checks.yml` must be green (the eval gate spends real Claude calls: it runs on the pull request as usual).

## Phase 6 - first deploy: merge to `main` (AWS, in Actions; I stop)
Merge the pull request. Open the `deploy` run. **What to look for**, in order:
- [ ] `images`: "Configure AWS credentials" names the assumed role (no access key in the log); both pushes end with a digest and the tag is the 40-character commit; in ECR both repositories show that tag.
- [ ] `server`: the guard prints the group id and "no inbound rule open to the internet". Instance step prints one id, `t3.large`, 30 GB, tag `project=fde-course`. **If `run-instances` says `UnauthorizedOperation`** (likely `iam:PassRole`, or a tag condition), the log names the action: that is a person's job; I write the exact IAM statement and stop.
- [ ] SSM wait: the instance shows "Online" within about 5 minutes. If it never does, the instance profile or the agent is wrong; look at the `describe-instance-information` output the step prints.
- [ ] `deploy`: systems `--wait` finishes (Oracle takes a few minutes); `pipeline ok: N orders, M parcels`; `policy_index.py` stored 47 sections; `chat`, `widget`, `shadow` healthy; the check prints a reply with a source link.
- [ ] The whole log contains no `sk-ant` and no key; the run is green; total time written down (Oracle's first start is the slow part).
- [ ] If red: I read the log you paste, fix one cause per pull request.
**Stop.**

## Phase 7 - the second push, and the first shadow rows (AWS, in Actions; I stop)
- [ ] A small change (a comment in `README.md`) through a pull request. **Look for:** the instance is found, not created; only the app image changes (`systems` containers show "Running", not "Recreated", and their uptime is older than the deploy); the check is green; session memory loss is expected.
- [ ] Wait about 10 minutes, then start the workflow by hand with `report: true`. **Look for:** about five rows (one chat per 120 s); each has the customer's message, an action, an answer; chats older than 240 s show the agent's reply; no `would_have` entry says a draft or task was *written*.
- [ ] In ServiceNow's stand-in nothing new appears for these chats (it is not reachable from outside, so this is checked by the worker's tests, not by a look).
**Stop.**

## Phase 8 - rollback (AWS, in Actions; I stop)
- [ ] Start the workflow by hand with `commit` = the first deploy's sha. **Look for:** no `images` job (the tags already exist in ECR; if a tag is missing the run fails with the tag name); `docker compose ps` shows the images of that sha; the check is green; the shadow table keeps its rows (data is not touched).
- [ ] Start it again with the newest sha to roll forward.
**Stop.**

## Phase 9 - teardown and the notes (offline, then you run it)
- [ ] `docs/teardown.md` (linked from the README): the commands in order, each with what it removes and whether the deploy role may run it:
      1. the shadow report, saved first (`report: true` run, output copied to a file outside git);
      2. `aws ec2 terminate-instances --instance-ids <id>` (role may) - removes the server, its 30 GB disk (check `DeleteOnTermination`) and with them every container, the order store and the shadow rows;
      3. `aws ec2 describe-instances --filters Name=tag:project,Values=fde-course` shows `terminated`;
      4. ECR images and repositories, the SSM parameter, the instance profile and role, the OIDC provider, the repository variable (a person's job; the role cannot).
- [ ] README: a "Deploy" section (what a merge does, rollback, the report, cost: the server runs only while we work on it).
- [ ] Check (I run): fast tests; every command in the file names the id or tag it acts on; none can delete more than the tag `project=fde-course`.
  Step 2 is destroying; before it you decide, and the report from step 1 is the restore point. **Stop.**

## Rules for the whole plan
- Every model call goes through `llm.py` (`shadow.py` uses `answer()`, no direct call). The model name stays in its one constant.
- Shadow mode writes nothing into DemoStore's systems and sends nothing to a customer. The only write is into our own `shadow_chats`.
- A refund is only ever a draft that a person approves; shadow mode makes none.
- No secret in an image, a committed file or a log. `server.env` holds only labelled test values.
- No port is open to the internet; no SSH; commands go through SSM. The guard in Phase 5 enforces the first.
- Anything the role cannot do: I write the exact command and stop.
- Fast tests keep passing: `python -m pytest -q -m "not live"`. Pre-commit is never skipped. Shortcuts go to `docs/quick-fixes.md`.
- Nothing in this plan deletes or overwrites existing work, so no restore point is needed until Phase 9, step 2, which is yours.
