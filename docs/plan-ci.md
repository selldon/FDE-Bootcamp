# CI - plan

Builds `docs/brief-ci.md` (Day 9) in six small phases. Each phase ends in a check. Docker is denied to me here, and everything on
GitHub (push, pull request, settings, secrets) is yours: where a check needs either, I write the exact command and stop; you run it
and tell me the result. Offline checks (ruff, mypy, `python -m pytest -q -m "not live"`, `cd widget && npx tsc -b`, a YAML parse of
the workflow files) I run myself. One phase at a time; tick the boxes as tasks are done. Commits: one per phase, only when you ask
(pre-commit runs, never skipped).

First action after approval: save this text as `docs/plan-ci.md`, then Phase 1 only, then stop.

## Where we start (read from the code)

- There is no `.github/` yet. Branch is `ci-checks`; `main` is the target.
- pre-commit runs ruff, mypy, the fast tests and `npx tsc -b` (widget) with `exclude: ^(sandbox|builds)/`. CI must skip the same
  folders, or `ruff check .` and `mypy .` would scan the labs in `sandbox/.course/`.
- `requirements.txt` = `-r requirements-runtime.txt` + pytest, ruff, mypy, pre-commit, httpx. The eval job needs only the runtime file.
  Python 3.12; the widget builds with Node 22 (`npm ci` + `tsc -b`, lock file is committed).
- `replay.py` prints `ok`/`MISS` per conversation, `Score: N of 40`, drafts written (must be 0) and the conversations that needed a
  person but stayed. **It always exits 0**, so as it stands it cannot fail a job.
- The replay reads real systems, so it is not "no network": Ledgerline (Oracle, read-only account), our PostgreSQL (the order store
  filled by `pipeline.py`, and the policy index filled by `policy_index.py` from Confluence), and the embedding model (downloaded
  from the web; cache it). It writes only to fakes (drafts, ServiceNow, traces). ServiceNow, Atlas and Mailpit are not needed.
- **Blocker found:** on a fresh runner the store is empty and `pipeline.py` stops on its own freshness check (newest carrier file is
  2026-10-22, limit 30 h). `tools.clock` also reads the wall clock for the age of the news.
- `test_hard_messages_live.py` (10 messages x `RUNS = 3`, real Claude) runs on the autouse fakes from `conftest.py`: no systems, no Docker.

## Decisions made with you (2026-10-26)

1. **Pin the clock.** An optional env var `DEMOSTORE_NOW` (ISO instant; the CI value is `2026-10-22T05:00:00+00:00`, the same instant
   `conftest.py` uses) is read by `pipeline.main` and `tools.clock`. Unset = the wall clock, so production is unchanged. Nothing in
   `sandbox/systems/` is touched.
2. **Fork pull requests** get no secret, so the eval job fails at once with "a maintainer must run the eval from a branch in this
   repo" (no Claude call, no cost). Branch protection then blocks the merge.

Assumptions (tell me if wrong): the eval runs on every push to an open pull request (otherwise it would score old code), and a newer
push cancels the older run (`concurrency`); it never runs on a branch without a pull request. The eval waits for ruff/mypy/tests/tsc
to pass, so a red PR costs nothing. Actions are pinned by major version (`@v4`), not by SHA (a line for `quick-fixes.md`). The nightly
run reports failure the way GitHub does by default (an email to whoever last edited the schedule); no issue bot. The gate also fails
if drafts written is not 0 (the brief's "writes nothing").

## Phase 1 - the fast checks

- [x] Save this plan as `docs/plan-ci.md`.
- [x] `.github/workflows/checks.yml`: `on: pull_request` to `main`; `permissions: contents: read`; `concurrency` per PR with
      `cancel-in-progress`; `timeout-minutes` on each job.
  - job `python`: checkout, setup-python 3.12 with pip cache, `pip install -r requirements.txt`, `ruff check . --extend-exclude
    sandbox --extend-exclude builds`, mypy on the tracked `.py` files outside `sandbox/` and `builds/`, `python -m pytest -q -m "not live"`.
  - job `widget`: checkout, setup-node 22 with npm cache, `npm ci`, `npx tsc -b` in `widget/`.
  - no secrets anywhere in this file; no key in the environment.
- [x] Check (I run): the same ruff, mypy, pytest and tsc commands pass on the branch; both files parse as YAML (and `actionlint` if
      installed). Fix whatever the full-repo ruff/mypy run finds that pre-commit's per-file run did not.
- [x] **Check for you (GitHub):** done 2026-10-26, PR #1: `python` and `widget` green (the first run failed on `TRACE_HMAC_KEY`; fixed in conftest.py, not in the workflow). Push the branch and open a pull request; the checks `python` and `widget` appear and go green.
  ```
  git push -u origin ci-checks
  gh pr create --base main --head ci-checks --title "CI: checks on every pull request" --body "Phase 1: fast checks"
  gh pr checks --watch
  ```
  **Stop.**

## Phase 2 - the gate and the clock, in code (offline)

- [x] `replay.py`: a pure `gate(runs, drafts)` that returns the failures: score below `GOAL = 36`, any conversation that needed a person
      and stayed, any draft written. `python replay.py --gate` prints `GATE: pass` or `GATE: fail` with the `MISS` ids and the stayed
      conversations, and exits 1 on fail. Without `--gate` the laptop behaviour is unchanged (exit 0).
- [x] `pipeline.run` and `tools.clock` read `DEMOSTORE_NOW` through `config.now()` (one helper, one place); unset = today's behaviour.
- [x] Fast tests in `test_replay.py` (the gate: 36 passes, 35 fails, a stayed conversation fails, a draft fails) and for the clock
      (set = fixed instant, unset = wall clock). Each names the brief line it serves.
- [x] Check (I run): fast tests (769), ruff, mypy green. **Stop.**

## Phase 3 - the replay against the systems (you run it on your laptop first)

- [x] Write the exact sequence the runner will run, as a script-free list of commands in this plan, and check it on your machine
      before it goes into a workflow (the same systems the course uses; I do not start them).
- [x] **Check (run on the laptop by me, 2026-10-26; no Docker command was needed, the systems were already up):**
  ```
  export DEMOSTORE_NOW=2026-10-22T05:00:00+00:00
  python pipeline.py            # expect: pipeline ok (this also closes the open "pipeline ok" of plan-containers)
  python policy_index.py        # 47 sections
  python replay.py --gate       # real Claude, a few cents; expect GATE: pass and the score
  ```
  Note: `pipeline.py` reloads your local order store (its normal write, idempotent). Tell me the score and the time; they fix the
  README numbers.
  **Result:** `pipeline ok: 33 orders, 33 parcels` (0.6 s); `policy_index.py`: 47 sections, code and pages agree (0.8 s);
  `replay.py --gate`: **38 of 40** (misses C17 and C26, both `hand_off` where the label says otherwise), policy 8 of 8, drafts 0, nobody
  who needed a person stayed, `GATE: pass`. The replay took **7 s**, 79 Claude calls, **about $0.38** (tokens x `llm.py` prices). These
  are the README numbers; the runner adds the time to start the systems (Oracle) and to pull images, measured in Phase 4.
  Restore point taken first (the load overwrites the store): all six tables of the `product` database as JSON in the session
  scratchpad (`product-db-before-phase3.json`; 33 orders, 33 parcels, 47 sections, 5 load runs). The counts after were the same.
  Side effect to know: the pinned clock wrote `2026-10-22T05:00Z` as the last load's time in `load_state`; the next hourly job rewrites it.
  **Stop.**

## Phase 4 - the eval job

- [x] `.github/workflows/eval.yml` (`workflow_call`) so the PR run and the nightly share one definition. Job `eval`:
  - first step, only on a pull request from a fork: print the message and `exit 1`.
  - checkout, setup-python, `pip install -r requirements-runtime.txt`, cache `FASTEMBED_CACHE_PATH`.
  - `docker compose -f sandbox/systems/compose.yaml up -d --wait ledgerline carrier ourdb confluence` (Oracle takes a minute or two).
  - job-level `env`: the test values from `.env.example` (they are not secrets) + `DEMOSTORE_NOW` + a throwaway `TRACE_HMAC_KEY`.
  - steps `python pipeline.py` and `python policy_index.py`: **no key in their environment**.
  - step `python replay.py --gate`: the only step with `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` (GitHub masks it; nothing
    echoes the environment; no `set -x`).
  - on failure: `docker compose logs` (the systems hold only test data), and the replay output stays in the log with the `MISS` ids.
  - `permissions: contents: read`; `timeout-minutes: 20`.
- [x] `checks.yml` gets job `eval`: `uses: ./.github/workflows/eval.yml`, `needs: [python, widget]`, and passes only `ANTHROPIC_API_KEY` (not `secrets: inherit`, which would hand over every secret). The check is named `eval / replay`.
- [x] Check (I run): YAML parses; the key is in three places only (declared, passed by the caller, the replay step's `env`). **Check for you (GitHub):**
  ```
  git push
  gh pr checks --watch        # eval runs after python and widget; read the log: score line, GATE: pass, no key in it
  gh run view --log | grep -c "sk-ant"      # must print 0
  ```
  **Result (2026-10-26, PR #1, push 933745a):** `python` 47 s, `widget` 11 s, `eval / replay` **1 m 36 s**, all green. In the log: systems
  started in about 56 s (Oracle is the slow one), `pipeline ok: 33 orders, 33 parcels`, 47 sections stored, `Score: 39 of 40`
  (miss C26), policy 8 of 8, drafts 0, nobody left with the assistant, `GATE: pass`. `sk-ant` appears 0 times in the log; the key shows
  once as `ANTHROPIC_API_KEY: ***`, on the replay step only. The same code scored 38 on the laptop and 39 here (the model varies by
  one or two a run), so the goal of 36 leaves a margin of 2-3.
  **Stop.**

## Phase 5 - the nightly run

- [x] `.github/workflows/nightly.yml`: `schedule: cron "17 2 * * *"` (UTC, off the hour) and `workflow_dispatch`; job 1 calls `eval.yml`;
      job 2 `hard-messages`: no Docker, `pip install -r requirements.txt`, `python -m pytest -m live test_hard_messages_live.py` with the
      key on that step only. Both jobs `permissions: contents: read`.
- [ ] Note for you: a schedule and a manual run work only once the file is on `main`, so this is checked after the first merge:
  ```
  gh workflow run nightly.yml --ref main
  gh run watch
  ```
  **Stop.**

## Phase 6 - the README section and the check of the check

- [x] README section "Checks on every pull request" (written 2026-10-26; the hard messages' time and cost say "not measured yet" until the first nightly run, then fill them in): what runs when (PR: `python`, `widget`, then `eval`; nightly: replay + hard
      messages), how long each takes, what one run costs, what to do when it is red (read the `MISS` ids, run `python replay.py` locally,
      do not retry until the cause is known; a fork PR needs a maintainer). Times and cost are **measured** from the first real runs, not
      guessed (the cost: the replay's token usage x the prices in `llm.py`).
- [x] `docs/quick-fixes.md` (four lines, one more than listed: the single-sample eval): actions pinned by major version not SHA; unpinned requirements in CI; nightly alert is GitHub's default
      email; `DEMOSTORE_NOW` is a test hook in production code.
- [x] **Settings for you (GitHub; not mine to change)** (the rule on `main` was set by the author; the API echoed the required checks `python`, `widget`, `eval / replay`; the other settings below were not read by me): Settings, Branches, rule for `main`: require a pull request; require status
      checks `python`, `widget`, `eval` to pass and the branch to be up to date; no bypass. Settings, Actions, General: "Require approval
      for first-time contributors" for fork PRs; workflow permissions read-only. Confirm the secret exists: `gh secret list`.
- [x] **The check of the check** (done 2026-10-26, PR #2 closed unmerged; result below). It was to be run by the author on a branch: I give you the one-line weakening (for example the return window in
      `returns.py`) and the commands; the pull request must turn `eval` red and name the conversations that failed; close it unmerged:
  ```
  git switch -c break-the-rule && <weaken one rule> && git commit -am "break a rule on purpose" && git push -u origin break-the-rule
  gh pr create --base main --title "DO NOT MERGE: break a rule" --body "check of the check"
  gh pr checks --watch        # expect eval red, MISS ids in the log
  gh pr close --delete-branch
  ```

## Verification

Phase 1: green `python` and `widget` on a real pull request. Phase 4: green `eval` with the score and no key in the log. Phase 5: a
manual nightly run green after merge. Phase 6: the broken-rule PR is red and names the failed conversations.

## Result of the check of the check (2026-10-26, PR #2, commit f80b4bb)

The weakened rule: one line of the system prompt in `agent.py` ("Also call hand_off when the customer is angry or asks for a person"
became "Never call hand_off ..."). It passes ruff, mypy and the 769 fast tests, which do not pin the prompt, so `eval` is reached; a
rule that a fast test pins (the return window in `returns.py`) would turn `python` red and skip `eval`.

- `python` green (39 s), `widget` green (9 s), `eval / replay` **red** (2 m 5 s). The log: `Score: 35 of 40`, `GATE: fail`,
  `wrong: C03, C12, C17, C18, C26`, and `C03` and `C18` "need a person and stayed with the assistant". C17 and C26 also miss on a
  clean branch; C03 and C18 are the break. No `sk-ant` in the log.
- `gh pr merge 2 --merge` was refused: `mergeStateStatus=BLOCKED`, `main` unchanged at 8bc7de1. The pull request was closed and the branch deleted.
- The margin is thin: 35 against a goal of 36. The second rule (a conversation that needs a person and stayed) failed on its own too.
  See the last line of `docs/quick-fixes.md`.
