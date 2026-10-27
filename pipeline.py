"""The hourly pipeline: Ledgerline + the carrier's newest file -> the four checks -> the order store.

Ledgerline has no change time, so every run reads everything (spec-2). Nothing is written
unless all four checks pass; the write is one transaction that also records the run, and that
record is the watermark, so the watermark moves only after the commit. Run it with
`python pipeline.py`; the exit code is not zero when a check fails or a source cannot be read.
"""
import sys

import carrier
import checks
import config
import ledgerline
import store as order_store


class PipelineError(Exception):
    """A check failed or a source could not be used; nothing was written."""


def build_rows(orders, news):
    """Our order rows and parcel rows: Ledgerline's parcels plus the carrier's latest news for each."""
    latest = {}
    for n in news:  # the newest news per tracking number (the last one wins on a tie)
        if n["tracking"] not in latest or n["date"] >= latest[n["tracking"]]["date"]:
            latest[n["tracking"]] = n
    parcels = []
    for o in orders:
        for p in o["parcels"]:
            n = latest.get(p["tracking"], {})
            parcels.append({**p, "order_no": o["number"], "carrier_status": n.get("status"),
                            "place": n.get("place"), "pickup_point": n.get("pickup_point") or None,
                            "news_date": n.get("date")})
    return orders, parcels


def run_checks(orders, parcels, newest_news, db, now, file_date=None):
    """All the checks; a list of 'check: problem' lines, empty when the load may go on. `file_date` is the date in the
    newest file's name: after 03:00 UTC it must be today's, and if not, the message says the file is missing."""
    recent = db.recent_runs()
    known = {o["number"] for o in orders} | db.order_numbers()
    results = {
        "row count": (checks.check_row_count("orders", len(orders), [r[0] for r in recent])
                      + checks.check_row_count("parcels", len(parcels), [r[1] for r in recent])),
        "parcels known": checks.check_parcels_known(parcels, known),
        "statuses": checks.check_statuses(orders),
        "news fresh": checks.check_news_fresh(newest_news, now),
        "file arrived": checks.check_file_arrived(file_date, now) if file_date else [],
    }
    return [f"check '{name}' failed: {p}" for name, problems in results.items() for p in problems]


def run(db=None, orders=None, files=None, now=None):
    """One load. Returns (order rows, parcel rows) written; raises PipelineError, writing nothing."""
    db = db or order_store.Store()
    now = now or config.now()
    db.create_tables()
    db.watermark()  # the last good load; the new one is recorded by save() after the commit
    orders = ledgerline.all_orders() if orders is None else orders
    if files is None:
        with carrier.connect() as live:
            name, news = carrier.newest_rows(live)
    else:
        name, news = carrier.newest_rows(files)
    orders, parcels = build_rows(orders, news)
    problems = run_checks(orders, parcels, carrier.newest_news(news), db, now, carrier.file_date(name))
    if problems:
        raise PipelineError("; ".join(problems))
    db.save(orders, parcels, finished_at=now)
    return len(orders), len(parcels)


def main():
    try:
        n_orders, n_parcels = run()
    except (PipelineError, carrier.CarrierError, ValueError) as e:
        print(f"pipeline stopped, nothing written: {e}", file=sys.stderr)
        return 1
    print(f"pipeline ok: {n_orders} orders, {n_parcels} parcels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
