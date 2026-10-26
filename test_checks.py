from datetime import UTC, date, datetime, timedelta

import checks

DAY = date(2026, 10, 22)
START = datetime(2026, 10, 22, tzinfo=UTC)  # the start of the 22nd: IT14 counts from here


def test_row_count_in_band_passes():
    assert checks.check_row_count("orders", 33, [33, 32, 34]) == []


def test_row_count_far_from_normal_fails():
    assert checks.check_row_count("orders", 5, [33, 32, 34])
    assert checks.check_row_count("orders", 90, [33, 32, 34])


def test_row_count_band_edges_are_inside():
    assert checks.check_row_count("orders", 75, [100]) == []
    assert checks.check_row_count("orders", 125, [100]) == []
    assert checks.check_row_count("orders", 74, [100])
    assert checks.check_row_count("orders", 126, [100])


def test_first_run_needs_only_rows():
    assert checks.check_row_count("orders", 1, []) == []
    assert checks.check_row_count("orders", 0, [])
    assert checks.check_row_count("orders", 0, [33])


def test_parcels_known_in_batch_or_store():
    parcels = [{"tracking": "T1", "order_no": "A"}, {"tracking": "T2", "order_no": "B"}]
    assert checks.check_parcels_known(parcels, {"A", "B"}) == []
    problems = checks.check_parcels_known(parcels, {"A"})
    assert len(problems) == 1 and "T2" in problems[0]


def test_statuses():
    ok = [{"number": "1", "status": s} for s in ("new", "part shipped", "shipped", "delivered", "cancelled")]
    assert checks.check_statuses(ok) == []
    problems = checks.check_statuses(ok + [{"number": "9", "status": "lost"}])
    assert len(problems) == 1 and "'lost'" in problems[0]


def test_news_age_edge():
    assert checks.check_news_fresh(DAY, START + timedelta(hours=30)) == []  # exactly 30h: still fine
    assert checks.check_news_fresh(DAY, START + timedelta(hours=30, seconds=1))
    assert checks.check_news_fresh(DAY, START + timedelta(hours=29, minutes=59)) == []


def test_news_dated_the_22nd_turns_stale_at_06_00_on_the_23rd():
    assert checks.check_news_fresh(DAY, datetime(2026, 10, 23, 6, 0, tzinfo=UTC)) == []
    assert checks.check_news_fresh(DAY, datetime(2026, 10, 23, 6, 0, 1, tzinfo=UTC))
    # news from 00:05 may be 54 hours old at 06:00 on the 24th; the rule must not call it fresh
    assert checks.check_news_fresh(DAY, datetime(2026, 10, 24, 6, 0, tzinfo=UTC))


def test_news_today_is_fresh_and_none_fails():
    assert checks.check_news_fresh(DAY, START + timedelta(hours=5)) == []
    assert checks.check_news_fresh(None, START)
