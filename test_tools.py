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


# The 30-hour rule (B9, IT14): news dated 2026-10-21 ends at 2026-10-22 00:00 UTC.
END_OF_NEWS = datetime(2026, 10, 22, tzinfo=UTC)


def at(monkeypatch, delta):
    monkeypatch.setattr(tools, "clock", lambda: END_OF_NEWS + delta)


def test_news_at_29h59m_gives_the_date(monkeypatch):
    at(monkeypatch, timedelta(hours=29, minutes=59))
    parcel = delivery_status("EP-7718204", MAYA)
    assert parcel["date"] == "2026-10-21" and "offer_person" not in parcel
    order = find_order("DS-20417", MAYA)
    assert order["promised"] == "2026-10-19" and "offer_person" not in order


def test_news_at_30h01m_gives_no_date_and_the_flag(monkeypatch):
    at(monkeypatch, timedelta(hours=30, minutes=1))
    parcel = delivery_status("EP-7718204", MAYA)
    assert parcel["date"] is None and parcel["offer_person"] is True
    assert parcel["status"] == "in transit" and parcel["place"] == "Leeds depot"
    order = find_order("DS-20417", MAYA)
    assert order["promised"] is None and order["offer_person"] is True
    assert "2026-10-21" not in json.dumps(order) + json.dumps(parcel)


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
