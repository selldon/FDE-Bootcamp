"""Going live: the launch switch, the visitor's group, and the table both groups are written to.

`golive_settings` holds one row (the share of visitors, the intents that are live, on/off); the chat service reads it
at every request, so a change needs no deploy. `golive_chats` holds each chat once, for both groups, so the pilot
page can compare them. `FakeGoLiveStore` has the same interface for the fast tests.

A visitor's group comes from a keyed hash of the visitor id into BUCKETS buckets. The bucket never changes, so the
group never changes, and widening the share only moves the line: 5 % -> 25 % adds visitors to the assistant group
and never removes one.
"""
import hashlib
import hmac
from datetime import UTC, datetime

import psycopg
from psycopg import sql

import config

BUCKETS = 10_000
# The key of the hash. Changing it would reshuffle every visitor, so it is a constant, not a setting.
GROUP_KEY = b"demostore-golive-groups-v1"

ASSISTANT, CONTROL, PERSON = "assistant", "control", "person"
DEFAULTS = {"share": 0.05, "intents": ["order_status"], "on": False}  # off until someone switches it on

SETTING_FIELDS = ("share", "intents", "on", "changed_at")
CHAT_FIELDS = ("visitor_id", "chat_id", "group_name", "intent", "outcome", "handed_off", "input_tokens",
               "output_tokens", "cost", "simulated", "sim_day", "created_at")


def bucket(visitor_id, key=GROUP_KEY):
    """The visitor's bucket, 0 .. BUCKETS-1: the same id always gives the same one."""
    digest = hmac.new(key, str(visitor_id).encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") % BUCKETS


def group_of(visitor_id, share, key=GROUP_KEY):
    """"assistant" or "control". A bigger share only adds buckets, so the old assistant group stays in it."""
    return ASSISTANT if bucket(visitor_id, key) < round(share * BUCKETS) else CONTROL


def check_settings(share, intents, on):
    """The values cleaned; ValueError for a share outside 0..1 or an intent list that is not a list of names."""
    if isinstance(share, bool) or not isinstance(share, int | float) or not 0 <= share <= 1:
        raise ValueError("share must be a number from 0 to 1")
    if not isinstance(intents, list | tuple) or not all(isinstance(i, str) and i for i in intents):
        raise ValueError("intents must be a list of intent names")
    return float(share), list(dict.fromkeys(intents)), bool(on)


def route(store, visitor_id, intent):
    """Where a new chat goes. The settings are read now, at this request, never cached.

    "person": the switch is off, or this intent is not live (it goes to a person as it did before the assistant);
    "control": the visitor is in the control group (a person, and it is counted); "assistant": the visitor is in the
    assistant group.
    """
    settings = store.settings()
    if not settings["on"] or intent not in settings["intents"]:
        return PERSON
    return group_of(visitor_id, settings["share"])


def tables(settings="golive_settings", chats="golive_chats"):
    """The CREATE statements: new tables, nothing existing is touched."""
    s, c = sql.Identifier(settings), sql.Identifier(chats)
    return [sql.SQL("""CREATE TABLE IF NOT EXISTS {s} (
                id boolean PRIMARY KEY DEFAULT true CHECK (id),
                share double precision NOT NULL CHECK (share >= 0 AND share <= 1),
                intents text[] NOT NULL, "on" boolean NOT NULL, changed_at timestamptz NOT NULL)""").format(s=s),
            sql.SQL("""CREATE TABLE IF NOT EXISTS {c} (
                visitor_id text NOT NULL, chat_id text PRIMARY KEY,
                group_name text NOT NULL CHECK (group_name IN ('assistant', 'control', 'person')),
                intent text, outcome text, handed_off boolean NOT NULL DEFAULT false,
                input_tokens int, output_tokens int, cost numeric(12, 6),
                simulated boolean NOT NULL DEFAULT false, sim_day int,
                created_at timestamptz NOT NULL)""").format(c=c)]


class GoLiveStore:
    """The real tables in the `product` database."""

    def __init__(self, url=None, settings_table="golive_settings", chats_table="golive_chats", **connect_args):
        self.url = url or config.store_url()
        self.settings_name, self.chats_name = settings_table, chats_table
        self.settings_table, self.chats_table = sql.Identifier(settings_table), sql.Identifier(chats_table)
        self.connect_args = connect_args

    def _connect(self):
        return psycopg.connect(self.url, **self.connect_args)

    def create_tables(self):
        with self._connect() as conn:
            for statement in tables(self.settings_name, self.chats_name):
                conn.execute(statement)
            conn.execute(sql.SQL('INSERT INTO {s} (share, intents, "on", changed_at) VALUES (%s, %s, %s, %s) '
                                 "ON CONFLICT (id) DO NOTHING").format(s=self.settings_table),
                         (DEFAULTS["share"], DEFAULTS["intents"], DEFAULTS["on"], datetime.now(UTC)))

    def settings(self):
        """The one settings row, read now."""
        with self._connect() as conn:
            row = conn.execute(sql.SQL('SELECT share, intents, "on", changed_at FROM {s}').format(
                s=self.settings_table)).fetchone()
        if row is None:
            raise RuntimeError("golive_settings has no row: run create_tables()")
        return dict(zip(SETTING_FIELDS, row, strict=True))

    def set_settings(self, share=None, intents=None, on=None, now=None):
        """Change any of the three; what is left out stays. Returns the new settings."""
        current = self.settings()
        share, intents, on = check_settings(current["share"] if share is None else share,
                                            current["intents"] if intents is None else intents,
                                            current["on"] if on is None else on)
        with self._connect() as conn:
            conn.execute(sql.SQL('UPDATE {s} SET share = %s, intents = %s, "on" = %s, changed_at = %s').format(
                s=self.settings_table), (share, intents, on, now or datetime.now(UTC)))
        return self.settings()

    def save_chat(self, row):
        """Store a chat once; a chat id already there is left as it is. True if the row was new."""
        query = sql.SQL("INSERT INTO {t} ({cols}) VALUES ({vals}) ON CONFLICT (chat_id) DO NOTHING").format(
            t=self.chats_table, cols=sql.SQL(", ").join(map(sql.Identifier, CHAT_FIELDS)),
            vals=sql.SQL(", ").join(sql.Placeholder(f) for f in CHAT_FIELDS))
        with self._connect() as conn:
            return conn.execute(query, chat_row(row)).rowcount == 1

    def chats(self, simulated=None):
        """Every chat, oldest first (only the simulated or only the real ones if `simulated` is given)."""
        where = sql.SQL("") if simulated is None else sql.SQL("WHERE simulated = %s")
        with self._connect() as conn:
            cur = conn.execute(sql.SQL("SELECT {cols} FROM {t} {w} ORDER BY created_at, chat_id").format(
                cols=sql.SQL(", ").join(map(sql.Identifier, CHAT_FIELDS)), t=self.chats_table, w=where),
                () if simulated is None else (bool(simulated),))
            return [dict(zip(CHAT_FIELDS, r, strict=True)) for r in cur]


def chat_row(row):
    """A chat as it is stored: every column present, the flags real booleans, a group that exists."""
    if row.get("group_name") not in (ASSISTANT, CONTROL, PERSON):
        raise ValueError("a chat needs a group: assistant, control or person")
    return {f: row.get(f) for f in CHAT_FIELDS} | {
        "handed_off": bool(row.get("handed_off")), "simulated": bool(row.get("simulated")),
        "created_at": row.get("created_at") or datetime.now(UTC)}


class FakeGoLiveStore:
    """The same interface in memory."""

    def __init__(self):
        self.row = None
        self.rows = {}

    def create_tables(self):
        if self.row is None:
            self.row = {**DEFAULTS, "intents": list(DEFAULTS["intents"]), "changed_at": datetime.now(UTC)}

    def settings(self):
        if self.row is None:
            raise RuntimeError("golive_settings has no row: run create_tables()")
        return {**self.row, "intents": list(self.row["intents"])}

    def set_settings(self, share=None, intents=None, on=None, now=None):
        current = self.settings()
        share, intents, on = check_settings(current["share"] if share is None else share,
                                            current["intents"] if intents is None else intents,
                                            current["on"] if on is None else on)
        self.row = {"share": share, "intents": intents, "on": on, "changed_at": now or datetime.now(UTC)}
        return self.settings()

    def save_chat(self, row):
        data = chat_row(row)
        if data["chat_id"] in self.rows:
            return False
        self.rows[data["chat_id"]] = data
        return True

    def chats(self, simulated=None):
        pool = [r for r in self.rows.values() if simulated is None or r["simulated"] == bool(simulated)]
        return [dict(r) for r in sorted(pool, key=lambda r: (r["created_at"], r["chat_id"]))]

