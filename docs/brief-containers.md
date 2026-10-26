# Brief: the pilot in containers

Day 9. The pilot works on our laptops. DemoStore's IT will run it on their servers, so it must run there exactly as it runs
for us: one image, built once, with everything it needs. Settings, secrets and data come in from outside.

## What to build

1. **One image for our Python code**, from a `Dockerfile`: Python 3.12 slim, only the libraries the code needs to run
   (not pytest, ruff, mypy or pre-commit), our code, a user that is not root. The same image runs three ways:
   - the chat service (`uvicorn app:app`, port 8000);
   - the hourly jobs: `python pipeline.py` (the middleware reads Ledgerline and the carrier's file into the order store)
     and `python policy_index.py`;
   - the daily job: `python retention.py`.
2. **The widget in its own image**: built with Node, served by nginx. nginx passes `/chat`, `/verify` and `/erase` to the
   chat service by its service name.
3. **`compose.yaml`** that starts the chat service and the widget with one command, and runs a job with
   `docker compose run --rm`.
4. **Checks**: the image builds; `docker compose up` starts both; the widget on http://localhost:8080 answers a real chat;
   `docker compose run --rm jobs python policy_index.py --check` says that code and pages agree; a second `up` after a
   change rebuilds only what changed.

## Where the systems are

DemoStore's systems already run as containers of the compose project `systems` (its network is `systems_default`; the
services are `ledgerline`, `ourdb`, `carrier`, `mail`). Our containers join that network and reach them by name. The
ServiceNow and Confluence stand-ins run on this machine, on the ports in `.env`; containers reach them through
`host.docker.internal`.

## Limits

- No secret in an image or in `compose.yaml`: the key and the passwords come from `.env` when a container starts.
  A `.dockerignore` keeps `.env`, `data/*.jsonl`, `sandbox/`, `widget/node_modules` and the caches out of the build.
- No data in a container: the order store, the traces and the policy index stay in our PostgreSQL.
- The embedding model is not downloaded again on every start.
- Never start, stop or change the `systems` containers.
- Fast tests still pass outside Docker: `python -m pytest -q -m "not live"`.
