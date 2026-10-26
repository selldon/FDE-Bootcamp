# Brief: checks on every pull request

Day 9. Today our checks run on our laptops, through the pre-commit hook. Anyone can skip a hook on their own machine,
and nobody else sees the result. From now on every change reaches `main` through a pull request on GitHub, and GitHub
runs the checks itself. A change that breaks a rule we promised DemoStore cannot be merged.

## What to build

1. **A workflow for every pull request to `main`** (`.github/workflows/checks.yml`), on GitHub's own runners:
   - ruff, mypy and the fast tests (`python -m pytest -q -m "not live"`): no key, no network;
   - the widget: `npm ci` and `tsc` in `widget/`;
   - **the eval gate**: the replay of the 40 labeled conversations (`python replay.py`) with real Claude. It passes only
     at our goal: at least 36 of 40 right actions and no conversation that needs a person staying with the assistant.
     The replay needs DemoStore's systems; they start on the runner from `sandbox/systems/compose.yaml`.
2. **The key**: the repository secret `ANTHROPIC_API_KEY` (it exists). Only the eval job gets it. It never appears in a
   log, and a pull request from a fork does not get it.
3. **A nightly run** (a schedule) of the replay and the 10 hard messages, so a change in the model or in a policy page
   shows up even on a day nobody pushes.
4. **A short README section**: what runs when, how long it takes, what it costs per run, what to do when it is red.

## The check of the check

On a branch, weaken one rule we promised: for example the return window in `returns.py` or the hand-off rule in the
prompt. Open a pull request. The workflow must turn red and say which conversations failed. Then close it without merging.

## Limits

- The replay writes nothing: drafts, tasks and traces go to fakes, as on the laptop.
- Keep the eval job's cost low: one replay per pull request, not on every push to a branch without a pull request.
- Never print the key; never pass it to a step that does not call Claude.
- Changes to GitHub's repository settings (for example branch protection) are a person's job: write down which setting,
  and we set it.
