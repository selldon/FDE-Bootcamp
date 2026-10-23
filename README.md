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
