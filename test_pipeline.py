"""Fast tests of the hourly pipeline: fake Ledgerline orders, fake SFTP folder, FakeStore."""
import json
from datetime import UTC, date, datetime

import pytest

import pipeline
import store
from test_carrier import FakeFiles

NOW = datetime(2026, 10, 23, 2, 0, tzinfo=UTC)  # 26h after the start of the news date 2026-10-22 (IT14)
LATER = datetime(2026, 10, 23, 3, 0, tzinfo=UTC)
FILE = ("tracking,status,place,date\n"
        "EP-1,in transit,Leeds depot,2026-10-22\n"
        "EP-2,delivered,front door,2026-10-22\n")


def files(text=FILE):
    return FakeFiles({"carrier-2026-10-22.csv": text})


def orders():
    return [
        {"number": "A-1", "customer": "a@example.com", "market": "UK", "status": "shipped",
         "items": ["Dock"], "promised": "2026-10-25", "tracking": ["EP-1"],
         "parcels": [{"tracking": "EP-1", "carrier": "EP", "shipped": "2026-10-20"}]},
        {"number": "A-2", "customer": "b@example.com", "market": "UK", "status": "delivered",
         "items": ["Mouse"], "promised": "2026-10-20", "tracking": ["EP-2"],
         "parcels": [{"tracking": "EP-2", "carrier": "EP", "shipped": "2026-10-15"}]},
    ]


def snapshot(db):
    return json.dumps({"orders": db.orders, "parcels": db.parcels}, sort_keys=True, default=str)


def test_a_normal_run_fills_the_store():
    db = store.FakeStore()
    assert pipeline.run(db, orders(), files(), now=NOW) == (2, 2)
    assert db.order_for_customer("A-1", "a@example.com")["status"] == "shipped"
    parcel = db.parcel_for_customer("EP-1", "a@example.com")
    assert parcel["place"] == "Leeds depot" and parcel["news_date"] == "2026-10-22"
    assert db.watermark() == NOW


def test_a_second_run_with_nothing_new_changes_nothing():
    db = store.FakeStore()
    pipeline.run(db, orders(), files(), now=NOW)
    first = snapshot(db)
    pipeline.run(db, orders(), files(), now=LATER)
    assert snapshot(db) == first
    assert db.watermark() == LATER


def test_the_same_run_twice_leaves_the_store_identical():
    once, twice = store.FakeStore(), store.FakeStore()
    pipeline.run(once, orders(), files(), now=NOW)
    pipeline.run(twice, orders(), files(), now=NOW)
    pipeline.run(twice, orders(), files(), now=NOW)
    assert snapshot(once) == snapshot(twice)
    assert len(twice.recent_runs()) == 1


def test_a_failed_check_leaves_the_store_and_the_watermark(capsys):
    db = store.FakeStore()
    pipeline.run(db, orders(), files(), now=NOW)
    before = snapshot(db)
    bad = orders()
    bad[0]["status"] = "lost"
    bad[0]["items"] = ["Changed"]
    with pytest.raises(pipeline.PipelineError, match="statuses"):
        pipeline.run(db, bad, files(), now=LATER)
    assert snapshot(db) == before
    assert db.watermark() == NOW


def test_stale_carrier_news_stops_the_load():
    db = store.FakeStore()
    with pytest.raises(pipeline.PipelineError, match="news fresh"):
        pipeline.run(db, orders(), files(), now=datetime(2026, 10, 25, tzinfo=UTC))
    assert db.orders == {} and db.watermark() is None


def test_a_parcel_of_an_unknown_order_stops_the_load():
    db = store.FakeStore()
    bad = orders()
    bad[0]["parcels"][0]["tracking"] = "EP-1"
    parcels_known = pipeline.run_checks(
        bad, [{"tracking": "EP-9", "order_no": "Z-9"}], date(2026, 10, 22), db, NOW)
    assert any("parcels known" in p for p in parcels_known)


def test_a_row_count_far_from_normal_stops_the_load():
    db = store.FakeStore()
    pipeline.run(db, orders(), files(), now=NOW)
    with pytest.raises(pipeline.PipelineError, match="row count"):
        pipeline.run(db, orders()[:1], files(), now=LATER)
    assert len(db.orders) == 2


def test_main_exits_non_zero_and_names_the_check(monkeypatch, capsys):
    db = store.FakeStore()
    monkeypatch.setattr(pipeline.order_store, "Store", lambda: db)
    monkeypatch.setattr(pipeline.ledgerline, "all_orders", list)
    monkeypatch.setattr(pipeline.carrier, "connect", lambda: _Files(files()))
    assert pipeline.main() == 1
    assert "row count" in capsys.readouterr().err


def test_a_crash_in_the_middle_of_the_upserts_leaves_no_half_load():
    db = store.FakeStore()
    pipeline.run(db, orders(), files(), now=NOW)
    before = snapshot(db)
    changed = orders()
    changed[1]["status"] = "cancelled"

    class Crashing(dict):
        def __setitem__(self, key, value):
            if key == "EP-2":
                raise RuntimeError("connection lost")
            super().__setitem__(key, value)

    db.parcels = Crashing(db.parcels)
    with pytest.raises(RuntimeError):
        pipeline.run(db, changed, files(), now=LATER)
    assert snapshot(db) == before  # the changed order A-2 written before the crash is rolled back too
    assert db.watermark() == NOW


class _Files:
    def __init__(self, files):
        self.files = files

    def __enter__(self):
        return self.files

    def __exit__(self, *_):
        return False


def test_the_pipeline_uses_the_pinned_clock(monkeypatch):
    """Brief-ci: on a runner the carrier's files are old; with DEMOSTORE_NOW set the freshness check runs on that instant."""
    old = "tracking,status,place,date\nEP-1,in transit,Leeds depot,2020-01-01\n"
    pinned = "2020-01-01T10:00:00+00:00"
    with pytest.raises(pipeline.PipelineError, match="news fresh"):
        pipeline.run(store.FakeStore(), orders()[:1], files(old))
    monkeypatch.setenv("DEMOSTORE_NOW", pinned)
    db = store.FakeStore()
    assert pipeline.run(db, orders()[:1], files(old)) == (1, 1)
    assert db.watermark() == datetime(2020, 1, 1, 10, 0, tzinfo=UTC)
