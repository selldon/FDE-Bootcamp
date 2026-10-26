"""The four checks of every load (IT13): pure functions, each returns a list of problems.

An empty list means the check passed. The pipeline runs all four and stops the load if any
returns a problem; the message names the check.
"""
from datetime import UTC, datetime, time, timedelta
from statistics import median

import ledgerline

BAND = 0.25  # a run is normal within +-25% of the median of the recent runs (edges included)
MAX_NEWS_AGE = timedelta(hours=30)  # IT14: older than this is stale


def news_age(news_date, now):
    """How old a news dated `news_date` is: counted from the start of that day, UTC (IT14).

    The start of the day is the earliest the news can be from, so this is the largest possible
    age and old news never looks fresher than it is."""
    start = datetime.combine(news_date, time.min, tzinfo=UTC)
    return now - start


def check_row_count(name, count, recent_counts):
    """The number of rows is close to a normal run. With no history only 'more than zero' counts."""
    if count <= 0:
        return [f"{name}: no rows"]
    if not recent_counts:
        return []
    normal = median(recent_counts)
    low, high = normal * (1 - BAND), normal * (1 + BAND)
    if not low <= count <= high:
        return [f"{name}: {count} rows, a normal run has {low:g} to {high:g} (median {normal:g})"]
    return []


def check_parcels_known(parcels, order_numbers):
    """Every parcel belongs to an order in the batch or already in the store."""
    return [f"parcel {p['tracking']}: unknown order {p['order_no']}"
            for p in parcels if p["order_no"] not in order_numbers]


def check_statuses(orders):
    """Every order status is one of our words (the mapping table's values)."""
    ours = set(ledgerline.STATUS.values())
    return [f"order {o['number']}: status {o['status']!r} is not one of ours"
            for o in orders if o["status"] not in ours]


def check_news_fresh(newest_news, now):
    """The newest carrier news is at most 30 hours old; no news at all is a problem too."""
    if newest_news is None:
        return ["carrier: no news in the file"]
    age = news_age(newest_news, now)
    if age > MAX_NEWS_AGE:
        hours = age.total_seconds() / 3600
        return [f"carrier: newest news is dated {newest_news}, {hours:.1f} hours old (limit 30)"]
    return []
