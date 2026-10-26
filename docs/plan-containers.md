# Containers - plan

Builds `docs/brief-containers.md` (Day 9) in six small phases. Each phase ends in a check. Docker commands are denied to me in
this repo, so a check that needs Docker is written out as the exact command and I stop; you run it and tell me the result.
Offline checks (the fast tests `python -m pytest -q -m "not live"`, `cd widget && npx tsc -b`) I run myself.
One phase at a time. Tick the boxes as tasks are done. Commits: one per phase, only when you ask (pre-commit runs, never skipped).

First action after approval: save this text as `docs/plan-containers.md` (plan mode lets me write only the plan file now), then Phase 1.

## Where we start (read from the code)

- `app.py` serves `/chat`, `/verify/*`, `/erase/*`; its `__main__` binds 127.0.0.1:8000, so the container needs `uvicorn app:app --host 0.0.0.0`.
- Runtime needs only: anthropic, python-dotenv, fastapi, uvicorn, oracledb, psycopg[binary], paramiko, fastembed (checked against the
  imports of the non-test modules). `requirements.txt` also holds pytest, ruff, mypy, pre-commit, httpx (tests only).
- The code reads no file at run time except `data/outbox.jsonl` (append, `verify.py`). No `data/*.json` is needed in the image.
- `fastembed` caches the model in a temp folder by default; `embedder.MODEL_NAME` = `BAAI/bge-small-en-v1.5`.
- `config.py` reads everything from the environment (`load_dotenv` does not override it); `.env` holds 127.0.0.1 hosts and the
  published ports (carrier 2222, not 22). `STORE_URL` carries the PostgreSQL password inside the URL.
- The widget calls relative `/chat` and `/verify/*`; Vite proxies only `/chat` and `/verify`. Nothing in the widget uses `/erase`, nginx proxies it anyway (brief).
- Jobs: `pipeline.py` (Ledgerline + carrier -> order store), `policy_index.py` (`--check` is read-only), `retention.py` (deletes traces > 90 days).

## Decisions made with you (2026-10-26)

1. **Outbox:** `verify.py` is not changed. The image has a writable `/app/data` for the app user so `/verify/start` does not crash; the
   codes land in a file inside the container and are lost with it. One line in `docs/quick-fixes.md`. Sending them to Mailpit is a later job.
2. **Host values:** compose uses `env_file: [.env, .env.containers]` (later wins). `.env.containers` is gitignored and holds only what
   differs inside containers (`LEDGERLINE_DSN=ledgerline:1521/FREEPDB1`, `CARRIER_HOST=carrier`, `CARRIER_PORT=22`, `STORE_URL` to `ourdb`,
   `SERVICENOW_URL`/`CONFLUENCE_URL` via `host.docker.internal`). `.env.containers.example` is committed, with no real secrets. No code change.
3. **Embedding model:** downloaded at build time into `/opt/models` (`FASTEMBED_CACHE_PATH`), baked into the image.

Assumptions (tell me if wrong): scheduling the hourly and daily jobs is IT's cron calling `docker compose run --rm jobs ...` (no scheduler
container; the cron lines go in the README). Requirements stay unpinned as today (noted in quick-fixes). The `jobs` service is under a
compose profile so `up` does not start it.

## Phase 1 - the Python image
- [x] Save this plan as `docs/plan-containers.md`.
- [x] `requirements-runtime.txt` (the 8 libraries above); `requirements.txt` becomes `-r requirements-runtime.txt` plus pytest, ruff, mypy,
      pre-commit, httpx, so `pip install -r requirements.txt` still gives the dev setup. Look first at who reads `requirements.txt` (devcontainer, README, doctor).
- [x] `.dockerignore`: `.env`, `.env.*`, `data/*.jsonl`, `sandbox/`, `widget/node_modules`, `widget/dist`, `.git`, `.venv`, `__pycache__`,
      `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.trace`, `.vscode`, `.claude`, `builds`, plus the tests: `test_*.py`, `conftest.py`, `try_*.py`, `probe_live.py`, `docs`.
- [x] `Dockerfile`: `python:3.12-slim`; layers in this order so a code change redoes nothing heavy: requirements -> `pip install --no-cache-dir`
      -> model download (as the app user, or `chown` of `/opt/models`) -> `COPY --chown *.py` -> `/app/data` writable. User `app` (uid 10001), not root.
      `CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]`. The model name is repeated in the Dockerfile with a comment pointing to `embedder.py`;
      the offline check below catches a mismatch. If `import fastembed` fails on slim, add `libgomp1` (known risk with onnxruntime).
- [x] Offline check (I run): fast tests pass; `requirements-runtime.txt` covers the third-party imports of the runtime modules.
- [x] **Check for you (Docker):** done 2026-10-26, all passed (image 499 MB).
  ```
  docker build -t demostore-app .
  docker run --rm demostore-app id -u                                  # not 0
  docker run --rm demostore-app pip list | grep -iE "pytest|ruff|mypy|pre-commit"   # prints nothing
  docker run --rm demostore-app ls -A /app                             # no .env, no test_*.py, no sandbox
  docker run --rm demostore-app python -c "import app, pipeline, policy_index, retention"
  docker run --rm --network none demostore-app python -c "from embedder import embed; print(len(embed(['hello'])[0]))"   # 384, offline = model is in the image
  docker run --rm demostore-app sh -c "echo '{}' >> data/outbox.jsonl && echo writable"
  ```
  **Stop.**

## Phase 2 - the widget image
- [x] `widget/Dockerfile`: stage 1 `node:22-alpine`, `npm ci`, `npm run build`; stage 2 `nginx:alpine` with `dist` and our config. `widget/.dockerignore` (`node_modules`, `dist`).
- [x] `widget/nginx.conf`: serve the build on 80 with a fallback to `index.html`; `location ~ ^/(chat|verify|erase)` proxies to `http://chat:8000`
      with Docker's resolver (`resolver 127.0.0.11`, host in a variable) so nginx starts before the chat service and survives its restart with a new address.
- [x] Offline check (I run): `cd widget && npx tsc -b` and `npx vite build` pass (the build the image runs); fast tests pass.
- [x] **Check for you (Docker):** done 2026-10-26, passed.
  ```
  docker build -t demostore-widget ./widget
  docker run --rm demostore-widget nginx -t                            # "syntax is ok"
  docker run --rm demostore-widget sh -c "ls /usr/share/nginx/html && nginx -T | grep -E 'chat|verify|erase'"
  ```
  **Stop.**

## Phase 3 - compose.yaml
- [x] `compose.yaml`, project name `demostore`. `chat`: `build: .`, `image: demostore-app`, `env_file: [.env, .env.containers]`, networks `default` and
      `systems_default` (`external: true`; we never start it), `extra_hosts: host.docker.internal:host-gateway` (so it also works on Linux servers),
      healthcheck with Python's `urllib` on `/openapi.json` (no curl in slim). `widget`: `build: ./widget`, `8080:80`, `depends_on` chat healthy.
      `jobs`: same build and image, same env and networks, `profiles: [jobs]`, no ports, no restart.
- [x] No secret in the file: only names, ports and the two env files.
- [x] `.env.containers.example` (committed); `.gitignore`: `.env.containers`.
- [x] Offline check (I run): the YAML parses; grep shows no password or key in `compose.yaml`; fast tests pass.
- [x] **Check for you (Docker):** done 2026-10-26, passed. `cp .env.containers.example .env.containers` and fill it, then `docker compose config -q` (silent = valid), `docker compose config | grep -ci "sk-ant"` (0).
  **Stop.**

## Phase 4 - up and a real chat
- [x] **Check for you (Docker), systems already running:** done 2026-10-26: up healthy; /chat through nginx and the widget answered (14 days, source link). Found: `traces` table missing in `product` (UndefinedTable, replies not blocked) - `retention.py` creates it in Phase 5.
  ```
  docker compose up -d --build
  docker compose ps                                                    # chat healthy, widget up, jobs absent
  curl -s -X POST localhost:8080/chat -H 'content-type: application/json' -d '{"message":"Hi, what is your return window?"}'
  curl -s -X POST localhost:8080/verify/start -H 'content-type: application/json' -d '{"email":"nobody@example.com"}'   # {"session_id":...,"verified":false}
  docker compose logs chat | tail -20                                  # no traceback
  ```
  Then open http://localhost:8080 and send one message. The chat call uses the Claude key (a few cents). I fix what fails (config, network, nginx), one change per round.
  **Stop.**

## Phase 5 - the jobs
- [ ] Restore point first (global rule): the pipeline upserts the order store, the index rebuild replaces stale sections, retention deletes old traces. You dump
      before the first job that writes: `pg_dump -h 127.0.0.1 -U demostore product > ~/product-before-containers.sql`. I will say this again at the phase.
- [x] **Check for you (Docker):** done 2026-10-26. `--check` agrees; `policy_index.py` stored 47 sections; `retention.py` deleted 0 traces. `pipeline.py` reached Ledgerline and the carrier by name but stopped by its own freshness check (newest carrier news 2026-10-22, 114 h old, limit 30) and wrote nothing: the sandbox carrier files are old, not a container fault. "pipeline ok" is not yet seen; it needs a carrier file from this week (`sandbox/systems/carrier/make_nights.py`, a change in the systems folder, so the author's call).
  ```
  docker compose run --rm jobs python policy_index.py --check          # read-only; brief check: "return windows: code and pages agree"
  # after the dump:
  docker compose run --rm jobs python pipeline.py                      # "pipeline ok: N orders, M parcels" (Ledgerline + carrier + ourdb by name)
  docker compose run --rm jobs python policy_index.py                  # sections stored
  docker compose run --rm jobs python retention.py                     # "deleted N traces older than 90 days"
  ```
  **Stop.**

## Phase 6 - second `up` rebuilds only what changed, and the notes
- [x] README section "Run in containers": first start, the two env files, the jobs and the cron lines for IT, what is not in the image.
- [x] `docs/quick-fixes.md`: codes go to a file inside the container; requirements unpinned; no scheduler; `host-gateway` for `host.docker.internal`; `/erase` is proxied but the widget has no UI for it.
- [x] Offline check (I run): fast tests; `cd widget && npx tsc -b`.
- [x] **Check for you (Docker):** done 2026-10-26. Nothing changed: 13 layers CACHED, no container recreated. `app.py` touched: chat rebuilt from COPY on (pip and model layers CACHED) and recreated, the widget image not rebuilt. `down` removed only our two containers; the four `systems` containers kept running. Not shown: a widget-only change. The `/* touch */` comment is stripped by Vite, so the image stayed identical and nothing was recreated (correct); a real CSS rule (`.touch{color:red}`) was not run.
  ```
  docker compose up -d --build                                         # nothing changed: all CACHED, no container recreated
  echo "# touch" >> widget/src/App.css && docker compose up -d --build   # only the widget image rebuilds; chat is not recreated
  git checkout widget/src/App.css
  echo "# touch" >> app.py && docker compose up -d --build              # chat rebuilds from COPY on (pip and model layers CACHED); widget untouched
  git checkout app.py
  docker compose down                                                  # stops only our two services; `systems` is not touched
  ```
  **Stop.**

## Rules for the whole plan
- Never start, stop or change the `systems` containers; our compose project is `demostore`, so `down` cannot touch them.
- No secret in an image, in `compose.yaml` or in a committed file; `.env` and `.env.containers` stay out of git and out of the build.
- No data in a container: order store, traces and policy index stay in our PostgreSQL. The only file the app writes is the outbox (decision 1).
- Every model call still goes through `llm.py`; no change to the Python code is planned (if one turns out to be needed, it goes to you first).
- Fast tests keep passing outside Docker.
