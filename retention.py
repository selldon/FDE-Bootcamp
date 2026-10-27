"""Traces are kept 90 days (B23). Run daily by cron: `python retention.py`."""
from datetime import UTC, datetime, timedelta

import shadow
import traces

RETENTION_DAYS = 90


def purge(older_than_days=RETENTION_DAYS, now=None, sink=None):
    """Delete the traces older than `older_than_days`; return how many.

    The written rule: a trace is deleted when its age is MORE than 90 days (at < now - 90 days).
    A trace of exactly 90 days is kept; it goes on the next daily run.
    """
    now = now or datetime.now(UTC)
    return (sink or traces.sink()).delete_before(now - timedelta(days=older_than_days))


def purge_shadow(older_than_days=RETENTION_DAYS, now=None, store=None):
    """The same rule for the pilot's `shadow_chats`, by `opened_at`; the marks of the purged chats go with them.

    Returns how many chats were deleted. Deletes rows when it runs: take a `pg_dump` of `product` before the first real run.
    """
    now = now or datetime.now(UTC)
    return (store or shadow.ShadowStore()).delete_before(now - timedelta(days=older_than_days))


if __name__ == "__main__":
    traces.sink().create_tables()
    print(f"deleted {purge()} traces older than {RETENTION_DAYS} days")
    shadow_store = shadow.ShadowStore()
    shadow_store.create_tables()
    print(f"deleted {purge_shadow(store=shadow_store)} shadow chats (and their marks) older than {RETENTION_DAYS} days")
