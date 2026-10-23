"""Fast tests of the order store contract on the FakeStore, and of the SQL texts. No network."""
from datetime import UTC, date, datetime

import pytest

import store

ORDERS = [
    {"number": "ORD-1", "customer": "Ann@Example.com", "market": "UK", "status": "shipped",
     "promised": date(2026, 10, 25), "items": ["Dock", "Cable"]},
    {"number": "ORD-2", "customer": "bob@example.com", "market": "UK", "status": "new",
     "promised": None, "items": ["Monitor"]},
]
PARCELS = [
    {"tracking": "EP-1", "order_no": "ORD-1", "carrier": "EP", "shipped": date(2026, 10, 22),
     "carrier_status": "in transit", "place": "Leeds", "pickup_point": "", "news_date": date(2026, 10, 22)},
    {"tracking": "EP-2", "order_no": "ORD-1", "carrier": "EP", "shipped": "2026-10-22"},
]


def snapshot(s):
    return (dict(s.orders), dict(s.parcels))


def loaded():
    s = store.FakeStore()
    s.save(ORDERS, PARCELS)
    return s


def test_writing_the_same_rows_twice_leaves_the_same_store():
    s = loaded()
    first = snapshot(s)
    s.save(ORDERS, PARCELS)
    assert snapshot(s) == first
    assert len(s.orders) == 2 and len(s.parcels) == 2


def test_a_changed_row_replaces_the_old_one():
    s = loaded()
    s.save([{**ORDERS[1], "status": "shipped"}], [])
    assert s.order_for_customer("ORD-2", "bob@example.com")["status"] == "shipped"
    assert len(s.orders) == 2


def test_owner_check_holds_for_orders_and_parcels():
    s = loaded()
    assert s.order_for_customer("ORD-1", "ann@example.com")["number"] == "ORD-1"
    assert s.order_for_customer("ORD-1", "bob@example.com") is None
    assert s.order_for_customer("ORD-9", "ann@example.com") is None
    assert s.parcel_for_customer("EP-1", "ann@example.com")["order_no"] == "ORD-1"
    assert s.parcel_for_customer("EP-1", "bob@example.com") is None
    assert s.parcel_for_customer("EP-9", "ann@example.com") is None


def test_order_comes_back_with_its_parcels_and_iso_dates():
    order = loaded().order_for_customer("ORD-1", "ANN@example.com")
    assert order["promised"] == "2026-10-25"
    assert order["tracking"] == ["EP-1", "EP-2"]
    assert order["parcels"][0]["news_date"] == "2026-10-22"
    assert order["parcels"][1]["carrier_status"] is None


def test_runs_and_watermark():
    s = store.FakeStore()
    assert s.watermark() is None and s.recent_runs() == []
    t1 = datetime(2026, 10, 23, 10, tzinfo=UTC)
    t2 = datetime(2026, 10, 23, 11, tzinfo=UTC)
    s.save(ORDERS, PARCELS, t1)
    s.save(ORDERS[:1], [], t2)
    assert s.watermark() == t2
    assert s.recent_runs() == [(1, 0), (2, 2)]
    assert s.order_numbers() == {"ORD-1", "ORD-2"}


def test_a_bad_row_leaves_the_store_as_it_was():
    s = loaded()
    before = snapshot(s)
    with pytest.raises(KeyError):
        s.save([ORDERS[0], {"number": "ORD-3"}], [])
    assert snapshot(s) == before


def test_real_store_sql_is_bound_upsert_and_never_destructive():
    texts = store.TABLES + [store.UPSERT_ORDER, store.UPSERT_PARCEL, store.RECORD_RUN,
                            store.ORDER_FOR_CUSTOMER, store.PARCEL_FOR_CUSTOMER]
    for sql in texts:
        upper = sql.upper()
        for word in ("DROP", "TRUNCATE", "DELETE"):
            assert word not in upper
    assert all("IF NOT EXISTS" in t for t in store.TABLES)
    assert "ON CONFLICT (number) DO UPDATE" in store.UPSERT_ORDER
    assert "ON CONFLICT (tracking) DO UPDATE" in store.UPSERT_PARCEL
    assert "customer = %(customer)s" in store.ORDER_FOR_CUSTOMER
    assert "o.customer = %(customer)s" in store.PARCEL_FOR_CUSTOMER
