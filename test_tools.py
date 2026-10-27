"""Fast tests of the order tools: fake data only, no call to Claude."""
import json
from datetime import UTC, datetime, timedelta

import tools
from tools import delivery_status, find_order

MAYA = "maya.ross@example.com"


def test_no_order_data_before_the_code_is_checked():
    assert "error" in find_order("DS-20417", None)


def test_someone_elses_order_gives_nothing():
    assert "error" in find_order("DS-20417", "ben.taylor@example.com")


def test_the_owner_gets_the_order():
    assert find_order("DS-20417", "maya.ross@example.com")["status"] == "shipped"


def test_no_parcel_data_before_the_code_is_checked():
    assert delivery_status("EP-7718204", None) == {
        "error": "customer not verified yet"}


def test_someone_elses_parcel_gives_nothing():
    other = delivery_status("EP-7718204", "tom.baker@example.com")
    assert other == delivery_status("EP-0000000", MAYA)


def test_the_owner_gets_the_parcel():
    assert delivery_status("EP-7718204", MAYA)["place"] == "Leeds depot"


def test_an_unknown_parcel_gives_an_error():
    assert "error" in delivery_status("EP-0000000", MAYA)


# The 03:00 rule (B9, IT14, OQ-5): the carrier's night file is expected by 03:00 UTC. News dated the 21st is current until
# 03:00 UTC on the 22nd and old after it - not 30 hours after its start, which let the 22nd's news pass until 06:00 on the 23rd.
START_OF_NEWS = datetime(2026, 10, 21, tzinfo=UTC)


def at(monkeypatch, delta):
    monkeypatch.setattr(tools, "clock", lambda: START_OF_NEWS + delta)


def test_yesterdays_news_gives_the_date_until_03_00_utc(monkeypatch):
    at(monkeypatch, timedelta(hours=27))  # 03:00:00 on the 22nd: the file is not late yet
    parcel = delivery_status("EP-7718204", MAYA)
    assert parcel["date"] == "2026-10-21" and "offer_person" not in parcel
    order = find_order("DS-20417", MAYA)
    assert order["promised"] == "2026-10-19" and "offer_person" not in order


def test_yesterdays_news_gives_no_date_and_the_flag_after_03_00_utc(monkeypatch):
    at(monkeypatch, timedelta(hours=27, seconds=1))
    parcel = delivery_status("EP-7718204", MAYA)
    assert parcel["date"] is None and parcel["offer_person"] is True
    assert parcel["status"] == "in transit" and parcel["place"] == "Leeds depot"
    order = find_order("DS-20417", MAYA)
    assert order["promised"] is None and order["offer_person"] is True
    assert "2026-10-21" not in json.dumps(order) + json.dumps(parcel)


def test_the_morning_of_a_missing_night_is_old_even_though_the_news_is_only_29_hours_old(monkeypatch):
    """The drill (27 Oct): no file for the 23rd; at 05:00 on the 23rd the 22nd's news was 29 hours old and passed as fresh."""
    tools.get_store().parcels["EP-7718204"]["news_date"] = "2026-10-22"
    monkeypatch.setattr(tools, "clock", lambda: datetime(2026, 10, 23, 5, 0, tzinfo=UTC))
    parcel = delivery_status("EP-7718204", MAYA)
    assert parcel["date"] is None and parcel["offer_person"] is True
    monkeypatch.setattr(tools, "clock", lambda: datetime(2026, 10, 23, 2, 59, tzinfo=UTC))
    assert delivery_status("EP-7718204", MAYA)["date"] == "2026-10-22"  # the night file is not due yet


def test_news_two_days_old_is_old_at_any_hour(monkeypatch):
    at(monkeypatch, timedelta(hours=50))  # 02:00 on the 23rd
    assert delivery_status("EP-7718204", MAYA)["offer_person"] is True


def test_a_delivered_parcel_keeps_its_dates_however_old_the_news(monkeypatch):
    # B9, IT14: a delivered parcel's news is final, so the 30-hour rule applies only to the others.
    tom = "tom.baker@example.com"
    at(monkeypatch, timedelta(days=30))
    parcel = delivery_status("EP-7718001", tom)
    assert parcel["status"] == "delivered" and parcel["date"] == "2026-10-14"
    assert "offer_person" not in parcel
    order = find_order("DS-20388", tom)
    assert order["promised"] is not None and "offer_person" not in order


def test_another_customers_order_or_parcel_is_the_same_error_as_unknown():
    tom = "tom.baker@example.com"
    assert find_order("DS-20417", tom) == find_order("DS-00000", tom)
    assert delivery_status("EP-7718204", tom) == delivery_status("EP-0000000", tom)


def test_the_dates_in_the_result_come_from_the_store(order_store):
    order_store.parcels["EP-7718204"]["news_date"] = "2026-10-22"
    order_store.orders["DS-20417"]["promised"] = "2026-11-02"
    assert delivery_status("EP-7718204", MAYA)["date"] == "2026-10-22"
    assert find_order("DS-20417", MAYA)["promised"] == "2026-11-02"


def test_the_tools_do_not_read_the_old_files():
    assert not hasattr(tools, "ORDERS")


def test_the_tools_clock_follows_the_pinned_time(monkeypatch):
    """Brief-ci: the age of the carrier's news is read from the same pinned instant as the pipeline's freshness check."""
    from datetime import UTC, datetime
    monkeypatch.undo()  # the autouse fixtures replaced tools.clock; this test wants the real one
    monkeypatch.setenv("DEMOSTORE_NOW", "2026-10-22T05:00:00+00:00")
    assert tools.clock() == datetime(2026, 10, 22, 5, 0, tzinfo=UTC)
