"""Traces are kept 90 days (B23). Run daily by cron: `python retention.py`."""
from datetime import UTC, datetime, timedelta

import traces

RETENTION_DAYS = 90


def purge(older_than_days=RETENTION_DAYS, now=None, sink=None):
    """Delete the traces older than `older_than_days`; return how many.

    The written rule: a trace is deleted when its age is MORE than 90 days (at < now - 90 days).
    A trace of exactly 90 days is kept; it goes on the next daily run.
    """
    now = now or datetime.now(UTC)
    return (sink or traces.sink()).delete_before(now - timedelta(days=older_than_days))


if __name__ == "__main__":
    traces.sink().create_tables()
    print(f"deleted {purge()} traces older than {RETENTION_DAYS} days")
