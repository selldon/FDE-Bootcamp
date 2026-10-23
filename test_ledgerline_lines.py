"""Fast tests of the live money read (Phase 4): a fake connection, the kind mapping, the delivery date."""
import inspect
import re
from decimal import Decimal
from pathlib import Path

import pytest

import conftest
import kinds
import ledgerline
import store

FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|ALTER|CREATE)\b", re.IGNORECASE)
# (LN_NO, SKU_CD, ITEM_DESC, QTY, UNIT_PRC, TAX_AMT, CURR_CD, MKT_CD, CUST_TYP_CD)
LINES = {"DS-1": ("maya@example.com", [(1, "AER-14-LAP", "Aero 14 laptop", 1, 999.5, 199.9, "GBP", "UK", "C"),
                                       (2, "WEB-W1  ", "Webcam W1", 2, Decimal("40.00"), Decimal("16.00"), "GBP", "UK", "C")]),
         "DS-2": ("li@example.com", [(1, "XXX-NEW", "Something new", 1, 10, 2, "USD", "US", "B")])}
PARCELS = {"DS-1": [(1, "EP-1"), (2, "EP-1"), (2, "EP-2")], "DS-2": []}


class LinesCursor:
    def __init__(self, log):
        self.log, self.rows = log, []

    def execute(self, sql, binds=None):
        self.log.append((sql, binds))
        self.rows = []
        if binds is None:
            return
        owner, lines = LINES.get(binds["order_no"], (None, []))
        if owner != binds["customer"]:
            return
        if sql == ledgerline.ORDER_LINES:
            self.rows = list(lines)
        elif sql == ledgerline.LINE_PARCELS:
            self.rows = list(PARCELS.get(binds["order_no"], []))

    def fetchall(self):
        return self.rows


class LinesConnection:
    def __init__(self):
        self.log, self.closed, self.rolled_back = [], False, False

    def cursor(self):
        return LinesCursor(self.log)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def conn(monkeypatch):
    for name, value in {"LEDGERLINE_DSN": "d", "LEDGERLINE_USER": "u", "LEDGERLINE_PASSWORD": "p"}.items():
        monkeypatch.setenv(name, value)
    return LinesConnection()


def read(conn, number="DS-1", customer="maya@example.com"):
    return ledgerline.order_lines(number, customer, connect=lambda **_: conn)


# kinds.py

# The 20 SKUs read from the copy on 2026-10-23.
SKUS_IN_THE_COPY = sorted(conftest.SKU_OF.values())


@pytest.mark.parametrize("sku", SKUS_IN_THE_COPY)
def test_every_sku_in_the_copy_is_in_the_mapping(sku):
    assert kinds.kind(sku) in {"earbuds", "software", "other"}


def test_the_mapping_has_no_sku_that_the_copy_lacks():
    assert sorted(kinds.KINDS) == SKUS_IN_THE_COPY


def test_an_unknown_sku_gives_none_not_a_guess():
    assert kinds.kind("XXX-NEW") is None
    assert kinds.kind("EAR-BUDS-1") is None  # looks like earbuds; still not in the mapping


def test_the_mapping_is_marked_unconfirmed():
    assert kinds.UNCONFIRMED is True
    assert "UNCONFIRMED" in Path("kinds.py").read_text()


def test_the_kind_never_reads_the_description():
    source = Path("kinds.py").read_text()
    assert "ITEM_DESC" not in source.split('"""', 2)[2]  # only the docstring may name it
    assert list(inspect.signature(kinds.kind).parameters) == ["sku"]


# the live read

@pytest.mark.parametrize("sql", [ledgerline.ORDER_LINES, ledgerline.LINE_PARCELS])
def test_the_queries_only_read_with_binds_and_check_the_owner(sql):
    assert sql.lstrip().upper().startswith("SELECT") and not FORBIDDEN.search(sql)
    assert ":order_no" in sql and ":customer" in sql
    assert "LOWER(c.EMAIL_ADDR)" in sql


def test_the_session_is_read_only_and_the_binds_are_bound(conn):
    read(conn, customer="Maya@Example.com")
    assert conn.log[0][0] == "SET TRANSACTION READ ONLY"
    assert all(b == {"order_no": "DS-1", "customer": "maya@example.com"} for _, b in conn.log[1:])
    assert conn.rolled_back and conn.closed


def test_the_lines_come_in_our_shape_with_decimals(conn):
    order = read(conn)
    assert order["market"] == "UK" and order["currency"] == "GBP" and order["customer_type"] == "consumer"
    first, second = order["lines"]
    assert first["line"] == 1 and first["kind"] == "other" and first["quantity"] == 1
    assert first["unit_price"] == Decimal("999.5") and first["tax"] == Decimal("199.9")
    assert second["sku"] == "WEB-W1" and second["quantity"] == 2  # CHAR padding stripped
    assert all(isinstance(v, Decimal) for line in order["lines"] for v in (line["unit_price"], line["tax"]))


def test_a_line_with_two_parcels_and_a_parcel_on_two_lines(conn):
    first, second = read(conn)["lines"]
    assert first["tracking"] == ["EP-1"]
    assert second["tracking"] == ["EP-1", "EP-2"]


def test_a_line_with_no_parcel(conn):
    order = read(conn, "DS-2", "li@example.com")
    assert order["lines"][0]["tracking"] == []


def test_an_unknown_sku_has_kind_none(conn):
    assert read(conn, "DS-2", "li@example.com")["lines"][0]["kind"] is None


def test_another_customers_order_is_empty_as_an_unknown_one(conn):
    assert read(conn, "DS-1", "li@example.com") is None
    assert read(conn, "DS-9", "li@example.com") is None


def test_an_unknown_customer_type_code_is_an_error_that_names_it(conn):
    LINES["DS-3"] = ("z@example.com", [(1, "KEY-K2", "Keyboard K2", 1, 1, 0, "EUR", "DE", "Q")])
    try:
        with pytest.raises(ValueError, match="'Q'"):
            read(conn, "DS-3", "z@example.com")
    finally:
        del LINES["DS-3"]


@pytest.mark.parametrize("code,word", [("C", "consumer"), ("B", "business"), ("C ", "consumer")])
def test_every_customer_type_code_maps(code, word):
    assert ledgerline.customer_type_word(code) == word


def test_the_words_are_the_ones_returns_uses():
    import returns
    assert set(ledgerline.CUSTOMER_TYPE.values()) == returns.CUSTOMER_TYPES
    assert {k for k in kinds.KINDS.values()} <= returns.PRODUCTS


# the fake

@pytest.fixture
def fake():
    return conftest.seed_ledgerline(ledgerline.FakeLedgerline())


def test_the_fake_has_the_same_answers_as_the_real_read(fake):
    order = fake.order_lines("DS-20417", "Maya.Ross@example.com")
    assert order["lines"][0]["sku"] == "AER-14-LAP" and order["lines"][0]["kind"] == "other"
    assert isinstance(order["lines"][0]["unit_price"], Decimal)
    assert "customer" not in order
    assert fake.order_lines("DS-20417", "tom.baker@example.com") is None
    assert fake.order_lines("DS-0", "tom.baker@example.com") is None


def test_every_order_of_the_fakes_has_lines_with_known_kinds(fake):
    assert fake.orders
    assert all(line["kind"] is not None for o in fake.orders.values() for line in o["lines"])


# the delivery date, through the store

def test_a_delivered_line_has_the_news_date(fake, order_store):
    line = fake.order_lines("DS-20388", "tom.baker@example.com")["lines"][0]
    assert ledgerline.delivery_date(line, "tom.baker@example.com", order_store) == "2026-10-14"


def test_a_line_not_delivered_is_none_not_a_date(fake, order_store):
    line = fake.order_lines("DS-20417", "maya.ross@example.com")["lines"][0]  # in transit
    assert ledgerline.delivery_date(line, "maya.ross@example.com", order_store) is None


def test_a_line_with_no_parcel_is_none(order_store):
    line = {"tracking": []}
    assert ledgerline.delivery_date(line, "paul.martin@example.com", order_store) is None


def parcel(tracking, status, date):
    return {"tracking": tracking, "order_no": "DS-1", "carrier_status": status, "place": "x", "news_date": date}


def test_a_line_with_two_parcels_is_delivered_when_both_are_and_dated_by_the_last():
    db = store.FakeStore()
    db.save([{"number": "DS-1", "customer": "a@example.com", "market": "UK", "status": "delivered",
              "items": ["x"]}],
            [parcel("T1", "delivered", "2026-10-10"), parcel("T2", "delivered", "2026-10-12")])
    line = {"tracking": ["T1", "T2"]}
    assert ledgerline.delivery_date(line, "a@example.com", db) == "2026-10-12"
    db.save([], [parcel("T2", "in transit", "2026-10-12")])
    assert ledgerline.delivery_date(line, "a@example.com", db) is None


def test_another_customers_parcel_gives_no_date(fake, order_store):
    line = fake.order_lines("DS-20388", "tom.baker@example.com")["lines"][0]
    assert ledgerline.delivery_date(line, "maya.ross@example.com", order_store) is None
