# Build 1 - plan

Builds `docs/spec.md` (B1-B6, IT1-IT8, goal G1) in small phases. Each phase ends in a check we can run: the fast tests
(`python -m pytest -q -m "not live"`, also run by pre-commit with ruff, mypy, tsc) or the replay of the 40 conversations
(`python replay.py`). Tick the boxes as each task is done. One phase at a time; stop after each one.

## Where we start

Done: `llm.py` adapter (`ask`), `intent.py`, `tools.py` (`find_order`, `delivery_status`), `agent.py` loop, `app.py`
(`/chat`, sessions, AI notice), React widget, fakes in `data/`, three fast tests.

Gaps found while reading the code (each is closed by a phase below):
- `delivery_status` has no customer check: it returns any parcel to anyone, verified or not (breaks B1, B6, IT2).
- `agent.py` calls `client.messages.create` itself, not through `llm.py` (breaks IT7, and blocks fast tests with a fake model).
- No one-time code, so `SESSIONS[...]["customer"]` is always `None`: nobody can see an order.
- No `hand_off` tool, no cases file, no ten-round limit (B4, B5, IT5, IT6).
- No `replay.py` (IT8). Every test in `test_app.py` is `live`, so the chat service has no fast test.

Rule for the whole build: `data/conversations.json` is the only set we tune on. `data/held_out.json` is not opened
until the last phase, once.

## Phase 1 - the order tools respect the locks (B1, B6, IT1, IT2)
- [x] `delivery_status(tracking, customer)`: no customer -> error with no data; a tracking number that is not on one of this customer's orders -> the same "no such parcel" error as an unknown one. The model's tool schema still takes only `tracking`.
- [x] `agent.run_tool` passes the session's customer to both tools.
- [x] Fast tests in `test_tools.py`: unverified gets nothing from `delivery_status`; someone else's parcel gets nothing; the owner gets the carrier row; an unknown parcel gets an error.
- [x] Check: fast tests pass.

## Phase 2 - every model call goes through `llm.py` (IT7)
- [x] `llm.chat(system, tools, messages, usage)` wraps the tool-using call; `agent.py` stops importing `client`.
- [x] `conftest.py` with a scripted fake model (a list of canned responses: tool_use, then text) for fast tests.
- [x] Fast tests of the loop with the fake: tool_use -> tool result -> final text. `test_unverified_chat_gets_no_order_data`: a chat with no customer asks `find_order` for a real order and the tool result sent back holds no order data (B1 -> IT2).
- [x] Check: fast tests pass; `grep -n "client.messages" *.py` finds only `llm.py`.

## Phase 3 - the one-time code (B1, IT3)
- [x] `verify.py`: `start(email)` writes a six-digit code to `data/outbox.jsonl` only for an email that has orders, and answers the same either way (no hint who is a customer); `check(email, code)`. Valid 10 minutes, 3 tries, then dead. Clock injectable.
- [x] `.gitignore`: `data/outbox.jsonl`, `data/cases.jsonl`.
- [x] Fast tests: right code works; wrong code x3 locks even the right one; expired code fails; unknown email writes nothing and looks the same.
- [x] Check: fast tests pass.

## Phase 4 - verification in the chat service and the widget (B1, B2, B6)
- [x] `POST /verify/start` and `POST /verify/check` on the session; `session["customer"]` is set only by a successful check, never by the model or the message text.
- [x] Widget: a "verify" step (email, then code) before order questions; `tsc` clean.
- [x] Fast tests of `/chat` with the fake model: unverified -> no order data in the reply path; verified owner -> status and promised date; asking for another customer's order -> nothing (B6). Keep the existing live tests in `test_app.py`.
- [x] Check: fast tests pass; `cd widget && npx tsc -b` clean; one manual run (start API and widget, read the code from `data/outbox.jsonl`).

## Phase 5 - hand-off to a person (B4, B5, IT5, IT6)
- [ ] `hand_off(summary)` tool: appends a case to `data/cases.jsonl` with the summary and the chat so far (the history comes from the session, not from the model); the reply says a person will take over.
- [ ] Loop stops after ten rounds and opens a case the same way.
- [ ] `answer()` returns reply + action (`hand_off`, `give_status`, or plain reply) + rounds, so the replay can score it; `app.py` and `try_agent.py` updated.
- [ ] Fast tests with the fake model: hand_off writes the case with the full history; the tenth round opens a case; the reply tells the customer.
- [ ] Check: fast tests pass.

## Phase 6 - the replay (IT8, G1)
- [ ] `score()` as a pure function: maps labels of later intents (`answer_policy`, `answer_product`, `start_return`, `check_buyer_role`) to `hand_off`; fast test on it.
- [ ] `replay.py`: 40 conversations from `data/conversations.json`, each as a verified session of the order's owner (a fixed default customer when the message has no order number), run in parallel; prints action per conversation, score of 40, and every conversation with `needs_human` that stayed with the assistant. It never opens `held_out.json`.
- [ ] First run, no tuning: write the baseline score and the misses at the bottom of this file.
- [ ] Check: `python replay.py` runs end to end and prints the baseline.

## Phase 7 - prompt and tool descriptions until G1 holds (B2, B3, B5)
- [ ] System prompt: ask for the order number when there is none (B3); anything this build does not cover -> `hand_off`, no answer attempted (B5); an angry or asking customer -> `hand_off`; dates and statuses only from tools; no promises about money.
- [ ] One change at a time, replay after each, note the score here.
- [ ] Check: replay shows at least 36 of 40, and zero conversations that need a person staying with the assistant. If it does not, we stop and look at the misses before changing anything else.

## Phase 8 - close Build 1
- [ ] `docs/quick-fixes.md` filled in (candidates: in-memory sessions, relative `data/` paths, one `classify` call per message that `/chat` does not need for its decision, fake email/ServiceNow files).
- [ ] Ask before the one run on `held_out.json`; record the score.
- [ ] Check: fast tests, ruff, mypy, tsc all green; final replay score written down.

## Decisions to confirm
1. The spec does not say how a customer names herself. Plan: she types her email in the widget; the code goes to that address (only if it has orders); verified means that email is the session's customer.
2. Action for scoring comes from code (which tool ran), not from the model's words. A plain reply with no tool counts as `ask_order_number`; on any other label it is a miss, which is exactly the B5 failure we want to see.
3. Commits: one per phase, only when you ask.
