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


# ---- the night file is expected by 03:00 UTC (OQ-5): after that, yesterday's news is old ----------------------------------

D21, D22, D23 = date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)


def utc(day, hour, minute=0, second=0):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=UTC)


def test_the_news_date_expected_flips_after_03_00_utc():
    assert checks.expected_news_date(utc(23, 2, 59, 59)) == D22
    assert checks.expected_news_date(utc(23, 3, 0, 0)) == D22  # "by 03:00": still on time at 03:00:00
    assert checks.expected_news_date(utc(23, 3, 0, 1)) == D23
    assert checks.expected_news_date(utc(23, 23, 59)) == D23


def test_yesterdays_news_is_old_after_03_00_and_todays_never_is():
    assert checks.news_is_old(D22, utc(23, 3, 0, 0)) is False
    assert checks.news_is_old(D22, utc(23, 3, 0, 1)) is True
    assert checks.news_is_old(D22, utc(23, 5)) is True  # the morning pin of the drill: 29 hours, but the file is overdue
    assert checks.news_is_old(D23, utc(23, 5)) is False
    assert checks.news_is_old(D21, utc(23, 2)) is True  # two days old is old at any hour


def test_the_clock_is_read_in_utc_whatever_its_zone():
    from datetime import timezone
    cest = timezone(timedelta(hours=2))
    assert checks.expected_news_date(datetime(2026, 10, 23, 4, 30, tzinfo=cest)) == D22  # 02:30 UTC
    assert checks.expected_news_date(datetime(2026, 10, 23, 5, 30, tzinfo=cest)) == D23  # 03:30 UTC


def test_the_hourly_check_says_the_file_is_missing():
    problems = checks.check_file_arrived(D22, utc(23, 3, 0, 1))
    assert len(problems) == 1
    assert ("carrier-2026-10-23.csv" in problems[0] and "missing" in problems[0] and "03:00 UTC" in problems[0]
            and "carrier-2026-10-22.csv" in problems[0])


def test_the_hourly_check_is_quiet_while_the_file_is_not_due_or_when_it_is_there():
    assert checks.check_file_arrived(D22, utc(23, 3, 0, 0)) == []
    assert checks.check_file_arrived(D22, utc(23, 2, 0)) == []
    assert checks.check_file_arrived(D23, utc(23, 3, 30)) == []
    assert checks.check_file_arrived(D23, utc(23, 23, 0)) == []
