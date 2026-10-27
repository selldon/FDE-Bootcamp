"""Shadow mode: the assistant answers live chats on the side, and nothing reaches the customer or DemoStore's systems.

This part is the store: `shadow_chats` in our own PostgreSQL holds each live chat once, with the answer
the assistant would have given and, later, what the human agent actually replied. `FakeShadowStore` has
the same interface for the fast tests.
"""
import json

import psycopg
from psycopg import sql

import config

# The columns, in order. Only the chat and what we made of it: no session id, no hash, no other customer data.
FIELDS = ("number", "opened_at", "opened_for", "market", "message", "intent", "action", "answer",
          "would_have", "state", "agent_reply", "answered_at")


def tables(name="shadow_chats"):
    """The CREATE statement; the name is a parameter so a live test can use its own table."""
    return [sql.SQL("""CREATE TABLE IF NOT EXISTS {t} (
        number text PRIMARY KEY, opened_at timestamptz NOT NULL, opened_for text NOT NULL, market text,
        message text NOT NULL, intent text, action text, answer text,
        would_have jsonb NOT NULL DEFAULT '{{}}'::jsonb, state text,
        agent_reply text, answered_at timestamptz NOT NULL)""").format(t=sql.Identifier(name))]


class ShadowStore:
    """The real table in the `product` database."""

    def __init__(self, url=None, table="shadow_chats", **connect_args):
        self.url = url or config.store_url()
        self.name = table
        self.table = sql.Identifier(table)
        self.connect_args = connect_args

    def _connect(self):
        return psycopg.connect(self.url, **self.connect_args)

    def create_tables(self):
        with self._connect() as conn:
            for statement in tables(self.name):
                conn.execute(statement)

    def watermark(self):
        """The newest `opened_at` stored, or None for an empty table."""
        with self._connect() as conn:
            return conn.execute(sql.SQL("SELECT max(opened_at) FROM {t}").format(t=self.table)).fetchone()[0]

    def save(self, row):
        """Store a chat once; a number already there is left as it is. True if the row was new."""
        data = {**row, "would_have": json.dumps(row.get("would_have") or {}, ensure_ascii=False)}
        query = sql.SQL("""INSERT INTO {t} ({cols}) VALUES ({vals}) ON CONFLICT (number) DO NOTHING""").format(
            t=self.table, cols=sql.SQL(", ").join(map(sql.Identifier, FIELDS)),
            vals=sql.SQL(", ").join(sql.Placeholder(f) for f in FIELDS))
        with self._connect() as conn:
            return conn.execute(query, {f: data.get(f) for f in FIELDS}).rowcount == 1

    def close(self, number, agent_reply):
        """Fill the agent's reply of a chat that has none yet; never replace one. True if it was filled."""
        with self._connect() as conn:
            return conn.execute(
                sql.SQL("UPDATE {t} SET agent_reply = %s, state = 'closed_complete' "
                        "WHERE number = %s AND agent_reply IS NULL").format(t=self.table),
                (agent_reply, number)).rowcount == 1

    def open_numbers(self):
        """The numbers of stored chats that still have no agent reply."""
        with self._connect() as conn:
            return [r[0] for r in conn.execute(
                sql.SQL("SELECT number FROM {t} WHERE agent_reply IS NULL ORDER BY opened_at").format(t=self.table))]

    def last(self, n=20):
        """The newest n rows, newest first, as dicts."""
        with self._connect() as conn:
            cur = conn.execute(sql.SQL("SELECT {cols} FROM {t} ORDER BY opened_at DESC, number DESC LIMIT %s").format(
                cols=sql.SQL(", ").join(map(sql.Identifier, FIELDS)), t=self.table), (n,))
            return [dict(zip(FIELDS, r, strict=True)) for r in cur]


class FakeShadowStore:
    """The same interface in memory."""

    def __init__(self):
        self.rows = {}

    def create_tables(self):
        pass

    def watermark(self):
        return max((r["opened_at"] for r in self.rows.values()), default=None)

    def save(self, row):
        if row["number"] in self.rows:
            return False
        self.rows[row["number"]] = {f: row.get(f) for f in FIELDS} | {"would_have": row.get("would_have") or {}}
        return True

    def close(self, number, agent_reply):
        row = self.rows.get(number)
        if row is None or row["agent_reply"] is not None:
            return False
        row["agent_reply"], row["state"] = agent_reply, "closed_complete"
        return True

    def open_numbers(self):
        return [r["number"] for r in sorted(self.rows.values(), key=lambda r: r["opened_at"]) if r["agent_reply"] is None]

    def last(self, n=20):
        return [dict(r) for r in sorted(self.rows.values(), key=lambda r: (r["opened_at"], r["number"]), reverse=True)[:n]]
