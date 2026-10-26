"""Every model call is recorded in the `traces` table (B22).

The prompt and the reply are stored after card numbers are masked. A trace that cannot be
written never blocks the customer's reply: the failure is counted and logged (plan-4, decision 1).
`FakeTraces` has the same interface for the fast tests.
"""
import contextvars
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import psycopg
from psycopg import sql

import config
from masking import mask_cards

log = logging.getLogger(__name__)

# The chat session of the call being made; /chat and the replay set it, so `llm` needs no new argument.
current_session: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_session", default=None)

# The keyed hash of the verified customer's email, set by /chat for the calls of her session (B23).
current_customer: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_customer", default=None)

FIELDS = ("at", "session_id", "customer_hash", "model", "prompt", "reply",
          "input_tokens", "output_tokens", "cost", "kind")

def customer_hash(email):
    """HMAC-SHA256 of the lower-cased email with the secret from the settings: the key to a customer's traces."""
    key = config.trace_key().encode()
    return hmac.new(key, email.strip().lower().encode(), hashlib.sha256).hexdigest()


def tables(traces="traces", erasures="erasures"):
    """The CREATE statements; the names are parameters so a live test can use its own tables."""
    return [
        sql.SQL("""CREATE TABLE IF NOT EXISTS {t} (
            id bigserial PRIMARY KEY, at timestamptz NOT NULL, session_id text, customer_hash text,
            model text NOT NULL, prompt text NOT NULL, reply text NOT NULL,
            input_tokens integer NOT NULL, output_tokens integer NOT NULL, cost numeric,
            kind text NOT NULL CHECK (kind IN ('ask', 'chat')))""").format(t=sql.Identifier(traces)),
        # The erasure log holds no email and no hash: only when, and how many rows.
        sql.SQL("""CREATE TABLE IF NOT EXISTS {e} (
            id bigserial PRIMARY KEY, at timestamptz NOT NULL, rows_deleted integer NOT NULL)""")
        .format(e=sql.Identifier(erasures)),
    ]


class Traces:
    """The real tables in our own PostgreSQL."""

    def __init__(self, url=None, traces="traces", erasures="erasures", **connect_args):
        self.url = url or config.store_url()
        self.table = sql.Identifier(traces)
        self.erasures = sql.Identifier(erasures)
        self.names = (traces, erasures)
        self.connect_args = connect_args

    def _connect(self):
        return psycopg.connect(self.url, **self.connect_args)

    def create_tables(self):
        with self._connect() as conn:
            for statement in tables(*self.names):
                conn.execute(statement)

    def add(self, row):
        query = sql.SQL("""INSERT INTO {t} (at, session_id, customer_hash, model, prompt, reply,
            input_tokens, output_tokens, cost, kind)
            VALUES (%(at)s, %(session_id)s, %(customer_hash)s, %(model)s, %(prompt)s, %(reply)s,
                    %(input_tokens)s, %(output_tokens)s, %(cost)s, %(kind)s)""").format(t=self.table)
        with self._connect() as conn:
            conn.execute(query, row)

    def fill_hash(self, session_id, hashed):
        """The earlier rows of a session get the customer's hash when she is verified."""
        with self._connect() as conn:
            conn.execute(sql.SQL("UPDATE {t} SET customer_hash = %s WHERE session_id = %s AND customer_hash IS NULL")
                         .format(t=self.table), (hashed, session_id))

    def delete_before(self, cutoff):
        """Delete traces older than the cutoff; return how many."""
        with self._connect() as conn:
            return conn.execute(sql.SQL("DELETE FROM {t} WHERE at < %s").format(t=self.table), (cutoff,)).rowcount

    def delete_customer(self, hashed, session_ids):
        """Delete one customer's traces, by her hash and by her session ids; return how many."""
        with self._connect() as conn:
            return conn.execute(
                sql.SQL("DELETE FROM {t} WHERE customer_hash = %s OR session_id = ANY(%s)").format(t=self.table),
                (hashed, list(session_ids))).rowcount

    def log_erasure(self, at, rows_deleted):
        with self._connect() as conn:
            conn.execute(sql.SQL("INSERT INTO {e} (at, rows_deleted) VALUES (%s, %s)").format(e=self.erasures),
                         (at, rows_deleted))


class FakeTraces:
    """The same interface in memory; `fail=True` makes every write fail."""

    def __init__(self, fail=False):
        self.rows = []
        self.erasures = []
        self.fail = fail

    def create_tables(self):
        pass

    def add(self, row):
        if self.fail:
            raise RuntimeError("trace table is down")
        self.rows.append(dict(row))

    def fill_hash(self, session_id, hashed):
        for row in self.rows:
            if row["session_id"] == session_id and row["customer_hash"] is None:
                row["customer_hash"] = hashed

    def delete_before(self, cutoff):
        kept = [r for r in self.rows if not r["at"] < cutoff]
        deleted, self.rows = len(self.rows) - len(kept), kept
        return deleted

    def delete_customer(self, hashed, session_ids):
        ids = set(session_ids)
        kept = [r for r in self.rows if r["customer_hash"] != hashed and r["session_id"] not in ids]
        deleted, self.rows = len(self.rows) - len(kept), kept
        return deleted

    def log_erasure(self, at, rows_deleted):
        self.erasures.append({"at": at, "rows_deleted": rows_deleted})


_sink = None
failures = 0  # trace writes that failed since the process started: a counted gap


def sink():
    """Where traces go: the real table unless a test or the replay put another one in."""
    global _sink
    if _sink is None:
        _sink = Traces()
    return _sink


def set_sink(new):
    global _sink
    _sink = new


def _plain(value):
    """Anything in a prompt or reply (dicts, SDK blocks, test blocks) as JSON-able data."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump())
    if hasattr(value, "__dict__"):
        return _plain(vars(value))
    return str(value)


def as_text(value):
    """The text to store: strings as they are, other data as JSON; card numbers masked last."""
    text = value if isinstance(value, str) else json.dumps(_plain(value), ensure_ascii=False)
    return mask_cards(text)


def record(kind, model, prompt, reply, usage, cost, now=None):
    """Write one trace. Never raises: a failed write is counted and logged."""
    global failures
    try:
        sink().add({
            "at": now or datetime.now(UTC), "session_id": current_session.get(), "customer_hash": current_customer.get(),
            "model": model, "prompt": as_text(prompt), "reply": as_text(reply),
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cost": cost, "kind": kind})
    except Exception as error:  # noqa: BLE001 - any table failure must not reach the customer
        failures += 1
        log.error("trace not written (%d so far): %s", failures, type(error).__name__)
