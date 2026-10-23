"""The order store: orders and parcels in our own PostgreSQL, in our shape and our words.

The chat tools read only this store. Every write is an upsert by key (order number,
tracking number) and one load is one transaction, so running the same load twice leaves
the store the same. `FakeStore` has the same interface for the fast tests.
"""
from datetime import UTC, date, datetime

import psycopg
from psycopg.types.json import Jsonb

import config

TABLES = [
    """CREATE TABLE IF NOT EXISTS orders (
        number text PRIMARY KEY, customer text NOT NULL, market text,
        status text NOT NULL, promised date, items jsonb NOT NULL DEFAULT '[]')""",
    """CREATE TABLE IF NOT EXISTS parcels (
        tracking text PRIMARY KEY, order_no text NOT NULL, carrier text, shipped date,
        carrier_status text, place text, pickup_point text, news_date date)""",
    """CREATE TABLE IF NOT EXISTS load_state (
        finished_at timestamptz PRIMARY KEY, order_rows integer NOT NULL, parcel_rows integer NOT NULL)""",
]

UPSERT_ORDER = """
INSERT INTO orders (number, customer, market, status, promised, items)
VALUES (%(number)s, %(customer)s, %(market)s, %(status)s, %(promised)s, %(items)s)
ON CONFLICT (number) DO UPDATE SET customer = EXCLUDED.customer, market = EXCLUDED.market,
    status = EXCLUDED.status, promised = EXCLUDED.promised, items = EXCLUDED.items
"""

UPSERT_PARCEL = """
INSERT INTO parcels (tracking, order_no, carrier, shipped, carrier_status, place, pickup_point, news_date)
VALUES (%(tracking)s, %(order_no)s, %(carrier)s, %(shipped)s, %(carrier_status)s, %(place)s,
        %(pickup_point)s, %(news_date)s)
ON CONFLICT (tracking) DO UPDATE SET order_no = EXCLUDED.order_no, carrier = EXCLUDED.carrier,
    shipped = EXCLUDED.shipped, carrier_status = EXCLUDED.carrier_status, place = EXCLUDED.place,
    pickup_point = EXCLUDED.pickup_point, news_date = EXCLUDED.news_date
"""

RECORD_RUN = """
INSERT INTO load_state (finished_at, order_rows, parcel_rows) VALUES (%s, %s, %s)
ON CONFLICT (finished_at) DO UPDATE SET order_rows = EXCLUDED.order_rows, parcel_rows = EXCLUDED.parcel_rows
"""

# The owner check is inside the query: another customer's order is no row at all.
ORDER_FOR_CUSTOMER = """
SELECT number, customer, market, status, promised, items FROM orders
WHERE number = %(number)s AND customer = %(customer)s
"""

PARCELS_OF_ORDER = """
SELECT tracking, order_no, carrier, shipped, carrier_status, place, pickup_point, news_date
FROM parcels WHERE order_no = %(number)s ORDER BY tracking
"""

PARCEL_FOR_CUSTOMER = """
SELECT p.tracking, p.order_no, p.carrier, p.shipped, p.carrier_status, p.place, p.pickup_point, p.news_date
FROM parcels p JOIN orders o ON o.number = p.order_no
WHERE p.tracking = %(tracking)s AND o.customer = %(customer)s
"""

ORDER_NUMBERS = "SELECT number FROM orders"
RECENT_RUNS = "SELECT order_rows, parcel_rows FROM load_state ORDER BY finished_at DESC LIMIT %s"
WATERMARK = "SELECT max(finished_at) FROM load_state"

PARCEL_FIELDS = ("tracking", "order_no", "carrier", "shipped", "carrier_status", "place",
                 "pickup_point", "news_date")


def _day(value):
    """A date (or a 'YYYY-MM-DD' text) as 'YYYY-MM-DD'; None stays None."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return value or None


def order_row(order):
    """An order from `ledgerline` in the store's shape (what both stores keep and return)."""
    return {"number": order["number"], "customer": order["customer"].lower(),
            "market": order.get("market"), "status": order["status"],
            "promised": _day(order.get("promised")), "items": list(order.get("items", []))}


def parcel_row(parcel):
    """A parcel in the store's shape: Ledgerline's fields plus the carrier's latest news, if any."""
    row = {f: parcel.get(f) for f in PARCEL_FIELDS}
    row["shipped"] = _day(row["shipped"])
    row["news_date"] = _day(row["news_date"])
    return row


def _parcel_from_db(record):
    return parcel_row(dict(zip(PARCEL_FIELDS, record)))


def _order_from_db(record, parcels):
    number, customer, market, status, promised, items = record
    return {"number": number, "customer": customer, "market": market, "status": status,
            "promised": _day(promised), "items": list(items),
            "tracking": [p["tracking"] for p in parcels], "parcels": parcels}


class Store:
    """The real order store in PostgreSQL. `options` is for libpq (the live test uses temp tables)."""

    def __init__(self, url=None, **connect_args):
        self.url = url or config.store_url()
        self.connect_args = connect_args

    def _connect(self):
        return psycopg.connect(self.url, **self.connect_args)

    def create_tables(self):
        with self._connect() as conn:  # commits on exit, rolls back on an error
            for statement in TABLES:
                conn.execute(statement)

    def save(self, orders, parcels, finished_at=None):
        """One load: upsert the orders and the parcels, record the run - all in one transaction."""
        order_rows = [order_row(o) for o in orders]
        parcel_rows = [parcel_row(p) for p in parcels]
        finished_at = finished_at or datetime.now(UTC)
        with self._connect() as conn:
            for row in order_rows:
                conn.execute(UPSERT_ORDER, {**row, "items": Jsonb(row["items"])})
            for row in parcel_rows:
                conn.execute(UPSERT_PARCEL, row)
            conn.execute(RECORD_RUN, (finished_at, len(order_rows), len(parcel_rows)))

    def order_for_customer(self, number, customer):
        """The order with its parcels, only if this customer owns it; None otherwise."""
        with self._connect() as conn:
            record = conn.execute(ORDER_FOR_CUSTOMER,
                                  {"number": number, "customer": customer.lower()}).fetchone()
            if record is None:
                return None
            parcels = [_parcel_from_db(r) for r in
                       conn.execute(PARCELS_OF_ORDER, {"number": number}).fetchall()]
        return _order_from_db(record, parcels)

    def parcel_for_customer(self, tracking, customer):
        """One parcel, only if it belongs to an order of this customer; None otherwise."""
        with self._connect() as conn:
            record = conn.execute(PARCEL_FOR_CUSTOMER,
                                  {"tracking": tracking, "customer": customer.lower()}).fetchone()
        return _parcel_from_db(record) if record else None

    def order_numbers(self):
        with self._connect() as conn:
            return {r[0] for r in conn.execute(ORDER_NUMBERS).fetchall()}

    def recent_runs(self, limit=10):
        """(order rows, parcel rows) of the last successful runs, newest first."""
        with self._connect() as conn:
            return [tuple(r) for r in conn.execute(RECENT_RUNS, (limit,)).fetchall()]

    def watermark(self):
        """The time of the last successful load, or None before the first."""
        with self._connect() as conn:
            return conn.execute(WATERMARK).fetchone()[0]


class FakeStore:
    """The same interface in memory: a dict per table."""

    def __init__(self):
        self.orders = {}
        self.parcels = {}
        self.runs = {}

    def create_tables(self):
        pass

    def save(self, orders, parcels, finished_at=None):
        # Build everything first, then apply: a bad row leaves the store as it was (one transaction).
        order_rows = [order_row(o) for o in orders]
        parcel_rows = [parcel_row(p) for p in parcels]
        finished_at = finished_at or datetime.now(UTC)
        for row in order_rows:
            self.orders[row["number"]] = row
        for row in parcel_rows:
            self.parcels[row["tracking"]] = row
        self.runs[finished_at] = (len(order_rows), len(parcel_rows))

    def _parcels_of(self, number):
        return [dict(p) for _, p in sorted(self.parcels.items()) if p["order_no"] == number]

    def order_for_customer(self, number, customer):
        row = self.orders.get(number)
        if row is None or row["customer"] != customer.lower():
            return None
        parcels = self._parcels_of(number)
        return _order_from_db((row["number"], row["customer"], row["market"], row["status"],
                               row["promised"], row["items"]), parcels)

    def parcel_for_customer(self, tracking, customer):
        row = self.parcels.get(tracking)
        owner = self.orders.get(row["order_no"]) if row else None
        if owner is None or owner["customer"] != customer.lower():
            return None
        return dict(row)

    def order_numbers(self):
        return set(self.orders)

    def recent_runs(self, limit=10):
        return [self.runs[t] for t in sorted(self.runs, reverse=True)[:limit]]

    def watermark(self):
        return max(self.runs, default=None)
