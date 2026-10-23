# DemoStore support assistant

The project of the Forward Deployed Engineer Bootcamp: a support and sales chat for DemoStore, built at the client,
step by step. Each day of the course starts from a tag, so you can always catch up:

    git checkout c1-d4-start

Put your Claude API key into `.env` (copy `.env.example`). Never commit `.env`.

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
