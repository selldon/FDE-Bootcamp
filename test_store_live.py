"""Live check: the order store on the real PostgreSQL. Run on request.

The tables are created as TEMPORARY tables (search_path = pg_temp), so the test leaves no rows
in the real store and needs no DELETE or DROP.
"""
from datetime import date

import pytest

import store

pytestmark = pytest.mark.live

ORDERS = [{"number": "T-1", "customer": "t@example.com", "market": "UK", "status": "shipped",
           "promised": date(2026, 10, 25), "items": ["Dock"]}]
PARCELS = [{"tracking": "T-EP-1", "order_no": "T-1", "carrier": "EP", "shipped": date(2026, 10, 22),
            "carrier_status": "in transit", "place": "Leeds", "pickup_point": "", "news_date": date(2026, 10, 22)}]


def test_write_twice_gives_the_same_store():
    s = store.Store(options="-c search_path=pg_temp")
    # Temp tables live per connection, so one connection serves the whole check.
    conn = s._connect()
    s._connect = lambda: _Shared(conn)  # type: ignore[method-assign]
    s.create_tables()
    s.save(ORDERS, PARCELS)
    first = (s.order_for_customer("T-1", "t@example.com"), conn.execute("SELECT count(*) FROM parcels").fetchone())
    s.save(ORDERS, PARCELS)
    second = (s.order_for_customer("T-1", "t@example.com"), conn.execute("SELECT count(*) FROM parcels").fetchone())
    print(first)
    assert first == second
    assert first[1] == (1,)
    assert s.order_for_customer("T-1", "other@example.com") is None
    conn.close()


class _Shared:
    """Lets `with self._connect()` reuse one connection: commit on success, roll back on error."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, *_):
        (self.conn.rollback if exc_type else self.conn.commit)()
