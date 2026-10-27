# Brief: the handover - a runbook and the first decision record

Day 11, after the two simulated weeks. In two weeks we leave DemoStore. Ravi Menon's team takes the assistant over: their
on-call engineer gets its alerts and owns the kill switch, and Marco Rossi's shift leads may ask them to use it. We stay
as backup for those two weeks only. Everything we know must live in this repository, next to the code, where they look.

## What to write

1. **`docs/runbook.md`**, for the person on call at three in the morning. One entry per alert that exists today, in the
   code, the jobs or the pages. Find them in the code; do not invent any. Each entry has the same parts: what it means
   and what customers feel right now; the first check, with the exact command or screen; how to act (the kill switch on
   the go-live page, or a step written out in full); how to see that it worked; who to call next, by role. Where
   something should raise an alert and nothing does, write it down as a gap, not as an entry.
2. **Owners after we leave**, at the end of the runbook: who changes the prompts, who adds labeled conversations to the
   evals, who approves a change to the return rules in Confluence, who confirms the hour the carrier's file is due, and
   who reads the go-live page each morning. Each answer is a role at DemoStore, never one of us.
3. **`docs/adr/0001-...md`**, one architecture decision record, for the decision a future engineer is most likely to
   question: the middleware, the only code that reads Ledgerline. The context, the decision in one sentence, the options
   we looked at, the reason, and the consequences, with what would make us decide again. Facts come from the code and
   the git history, not from memory.
4. **The check.** Someone who did not write the runbook runs every command in it against our local stack: read-only
   commands as written, and the switch off and on from the page. A command that fails or no longer exists is fixed in
   the runbook.
5. **Keeping it true.** A fast test fails when the runbook names a file, a script or an endpoint that no longer exists.
   The README links to the runbook and the ADR.

## Limits

- Every command is written out in full. No step like "check the logs and fix it".
- No keys, no secrets and no customer data in the documents; settings by name only.
- No change to product code, except the fast test. The systems in `sandbox/systems/` are never started, stopped or
  changed.
- Fast tests still pass: `python -m pytest -q -m "not live"`.
