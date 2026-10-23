"""Fast tests of the middleware queries: a fake connection, no network."""
import re
from datetime import datetime

import pytest

import ledgerline

FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|ALTER|CREATE)\b", re.IGNORECASE)
QUERIES = [ledgerline.ORDER, ledgerline.ORDER_ITEMS, ledgerline.ORDER_PARCELS,
           ledgerline.ALL_ORDERS, ledgerline.ALL_ITEMS, ledgerline.ALL_PARCELS]

HEADERS = [("DS-1", "maya@example.com", "UK", "F", datetime(2026, 10, 19)),
           ("DS-2", "li@example.com", "UK", "N", datetime(2026, 10, 25))]
ITEMS = [("DS-1", "Aero 14 laptop"), ("DS-1", "Dock"), ("DS-2", "Monitor")]
PARCELS = [("DS-1", "EP-1", "EP", datetime(2026, 10, 17)),
           ("DS-1", "EP-1", "EP", datetime(2026, 10, 17))]  # one parcel, two lines


class FakeCursor:
    def __init__(self, log):
        self.log, self.rows = log, []

    def execute(self, sql, binds=None):
        self.log.append((sql, binds))
        owned = (lambda r: r[0] == binds["order_no"]) if binds else (lambda r: True)
        mine = binds and binds["customer"]
        owner = {h[0]: h[1] for h in HEADERS}
        keep = lambda r: owned(r) and (not binds or owner[r[0]] == mine)
        if sql == ledgerline.ORDER or sql == ledgerline.ALL_ORDERS:
            self.rows = [h for h in HEADERS if keep(h)]
        elif sql in (ledgerline.ORDER_ITEMS, ledgerline.ALL_ITEMS):
            self.rows = [i for i in ITEMS if keep(i)]
        elif sql in (ledgerline.ORDER_PARCELS, ledgerline.ALL_PARCELS):
            self.rows = [p for p in PARCELS if keep(p)]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self):
        self.log, self.closed, self.rolled_back = [], False, False

    def cursor(self):
        return FakeCursor(self.log)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def conn(monkeypatch):
    for name, value in {"LEDGERLINE_DSN": "d", "LEDGERLINE_USER": "u",
                        "LEDGERLINE_PASSWORD": "p"}.items():
        monkeypatch.setenv(name, value)
    return FakeConnection()


@pytest.mark.parametrize("sql", QUERIES)
def test_queries_only_read(sql):
    assert sql.lstrip().upper().startswith("SELECT")
    assert not FORBIDDEN.search(sql)


@pytest.mark.parametrize("sql", [ledgerline.ORDER, ledgerline.ORDER_ITEMS,
                                 ledgerline.ORDER_PARCELS])
def test_per_order_queries_use_binds_and_check_the_owner(sql):
    assert ":order_no" in sql and ":customer" in sql


def test_the_session_is_read_only_and_closed(conn):
    ledgerline.order_for_customer("DS-1", "maya@example.com", connect=lambda **_: conn)
    assert conn.log[0][0] == "SET TRANSACTION READ ONLY"
    assert conn.rolled_back and conn.closed


def test_the_order_comes_in_our_shape(conn):
    order = ledgerline.order_for_customer("DS-1", "Maya@Example.com", connect=lambda **_: conn)
    assert order["status"] == "shipped" and order["promised"] == "2026-10-19"
    assert order["items"] == ["Aero 14 laptop", "Dock"]
    assert order["tracking"] == ["EP-1"] and len(order["parcels"]) == 1
    binds = conn.log[1][1]
    assert binds == {"order_no": "DS-1", "customer": "maya@example.com"}


def test_another_customers_order_returns_nothing(conn):
    assert ledgerline.order_for_customer("DS-1", "li@example.com",
                                         connect=lambda **_: conn) is None


def test_an_unknown_order_returns_nothing(conn):
    assert ledgerline.order_for_customer("DS-9", "li@example.com",
                                         connect=lambda **_: conn) is None


def test_all_orders(conn):
    orders = ledgerline.all_orders(connect=lambda **_: conn)
    assert [o["number"] for o in orders] == ["DS-1", "DS-2"]
    assert orders[1]["status"] == "new" and orders[1]["tracking"] == []


@pytest.mark.parametrize("code,word", [("N", "new"), ("S", "part shipped"),
                                       ("F", "shipped"), ("D", "delivered"),
                                       ("X", "cancelled")])
def test_every_code_maps(code, word):
    assert ledgerline.status_word(code) == word
    assert ledgerline.status_word(code + " ") == word  # CHAR padding


def test_an_unknown_code_is_an_error_that_names_it():
    with pytest.raises(ValueError, match="'Q'"):
        ledgerline.status_word("Q")
