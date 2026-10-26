"""Every model call is recorded in the `traces` table (B22).

The prompt and the reply are stored after card numbers are masked. A trace that cannot be
written never blocks the customer's reply: the failure is counted and logged (plan-4, decision 1).
`FakeTraces` has the same interface for the fast tests.
"""
import contextvars
import json
import logging
from datetime import UTC, datetime

import psycopg

import config
from masking import mask_cards

log = logging.getLogger(__name__)

# The chat session of the call being made; /chat and the replay set it, so `llm` needs no new argument.
current_session: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_session", default=None)

FIELDS = ("at", "session_id", "customer_hash", "model", "prompt", "reply",
          "input_tokens", "output_tokens", "cost", "kind")

TABLES = [
    """CREATE TABLE IF NOT EXISTS traces (
        id bigserial PRIMARY KEY, at timestamptz NOT NULL, session_id text, customer_hash text,
        model text NOT NULL, prompt text NOT NULL, reply text NOT NULL,
        input_tokens integer NOT NULL, output_tokens integer NOT NULL, cost numeric,
        kind text NOT NULL CHECK (kind IN ('ask', 'chat')))""",
]

INSERT = """
INSERT INTO traces (at, session_id, customer_hash, model, prompt, reply, input_tokens, output_tokens, cost, kind)
VALUES (%(at)s, %(session_id)s, %(customer_hash)s, %(model)s, %(prompt)s, %(reply)s,
        %(input_tokens)s, %(output_tokens)s, %(cost)s, %(kind)s)
"""


class Traces:
    """The real table in our own PostgreSQL."""

    def __init__(self, url=None, **connect_args):
        self.url = url or config.store_url()
        self.connect_args = connect_args

    def _connect(self):
        return psycopg.connect(self.url, **self.connect_args)

    def create_tables(self):
        with self._connect() as conn:
            for statement in TABLES:
                conn.execute(statement)

    def add(self, row):
        with self._connect() as conn:
            conn.execute(INSERT, row)


class FakeTraces:
    """The same interface in memory; `fail=True` makes every write fail."""

    def __init__(self, fail=False):
        self.rows = []
        self.fail = fail

    def create_tables(self):
        pass

    def add(self, row):
        if self.fail:
            raise RuntimeError("trace table is down")
        self.rows.append(dict(row))


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
            "at": now or datetime.now(UTC), "session_id": current_session.get(), "customer_hash": None,
            "model": model, "prompt": as_text(prompt), "reply": as_text(reply),
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cost": cost, "kind": kind})
    except Exception as error:  # noqa: BLE001 - any table failure must not reach the customer
        failures += 1
        log.error("trace not written (%d so far): %s", failures, type(error).__name__)
