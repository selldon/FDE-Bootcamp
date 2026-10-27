"""Shadow mode: the assistant answers live chats on the side, and nothing reaches the customer or DemoStore's systems.

`shadow_chats` in our own PostgreSQL holds each live chat once, with the answer the assistant would have
given and, later, what the human agent actually replied. `FakeShadowStore` has the same interface for the
fast tests.

The worker (`poll`) reads new live chats from ServiceNow with the reader account, answers each one with the
real `answer()` against fakes (drafts, tasks, cases, traces), and stores the result. Nothing is written to
ServiceNow, Ledgerline or the real trace table: the real writers are never wired in.

    python shadow.py            loop every SHADOW_EVERY seconds (default 30), touching a heartbeat file
    python shadow.py --once     one tick; exit 1 if it had an error
    python shadow.py report     the last 20 rows
"""
import base64
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

import config
import drafts
import refunds
import servicenow
import traces

log = logging.getLogger("shadow")

CHATS = "/api/now/table/interaction"
PAGE = 100
TIMEOUT = 10
RETRIES = 3  # tries for one call that gets 429

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

    def has(self, number):
        """True if a chat with this number is stored."""
        with self._connect() as conn:
            query = sql.SQL("SELECT 1 FROM {t} WHERE number = %s").format(t=self.table)
            return conn.execute(query, (number,)).fetchone() is not None

    def save(self, row):
        """Store a chat once; a number already there is left as it is. True if the row was new."""
        data = {**row, "would_have": json.dumps(row.get("would_have") or {}, ensure_ascii=False, default=str)}
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

    def has(self, number):
        return number in self.rows

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


class ReadError(RuntimeError):
    """A read from ServiceNow failed: `status` is the HTTP code (None for a timeout or a lost connection)."""

    def __init__(self, message, status=None, retry_after=1.0):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


def http_get(path):
    """One GET with the reader account; returns (parsed JSON). Never anything but a read."""
    settings = config.servicenow_reader()
    token = base64.b64encode(f"{settings['user']}:{settings['password']}".encode()).decode()
    request = urllib.request.Request(settings["url"] + path, method="GET",
                                     headers={"Authorization": f"Basic {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            wait = float(error.headers.get("Retry-After", 1))
        except (TypeError, ValueError):
            wait = 1.0
        raise ReadError(f"ServiceNow answered {error.code} to GET {path}", error.code, wait) from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ReadError(f"ServiceNow call GET {path} failed: {error}") from error


def fetch(client, path, sleep=time.sleep):
    """`client(path)`, waiting out a 429 (its Retry-After) up to RETRIES times; other errors go up to the tick."""
    for attempt in range(1, RETRIES + 1):
        try:
            return client(path)
        except ReadError as error:
            if error.status != 429 or attempt == RETRIES:
                raise
            sleep(min(error.retry_after, 5))


def query(client, text, sleep=time.sleep):
    """All rows of a query, page by page."""
    rows, offset = [], 0
    while True:
        params = urllib.parse.urlencode({"sysparm_query": text, "sysparm_limit": PAGE, "sysparm_offset": offset})
        page = fetch(client, f"{CHATS}?{params}", sleep).get("result", [])
        rows += page
        if len(page) < PAGE:
            return rows
        offset += PAGE


def stamp(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def parse_stamp(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def customer_message(transcript):
    """What the customer wrote: the transcript's first line without the 'Name: ' in front of it."""
    first = transcript.split("\nAgent:", 1)[0]
    return first.partition(": ")[2] or first


def agent_reply(transcript):
    """The text after 'Agent:', or None while no agent has answered."""
    if "\nAgent:" not in transcript:
        return None
    return transcript.split("\nAgent:", 1)[1].strip() or None


def plain(value):
    """A JSON-safe copy (amounts and dates become text)."""
    return json.loads(json.dumps(value, default=str))


def shadow_answer(chat, answerer):
    """Answer one live chat as its verified customer; return the row to store. Everything it would write goes to fakes."""
    fake_drafts, fake_snow, fake_traces = drafts.FakeDrafts(), servicenow.FakeServiceNow(), traces.FakeTraces()
    refunds.set_systems(None, fake_drafts, fake_snow)  # Ledgerline stays the read-only copy
    traces.set_sink(fake_traces)
    number, message = chat["number"], customer_message(chat.get("transcript", ""))
    ctx = refunds.Context(chat["opened_for"], f"shadow-{number}", market=chat.get("u_market") or None)
    token = traces.current_session.set(ctx.session_id)
    try:
        result = answerer(message, ctx)
    finally:
        traces.current_session.reset(token)
    return {"number": number, "opened_at": parse_stamp(chat["opened_at"]), "opened_for": chat["opened_for"],
            "market": chat.get("u_market") or None, "message": message, "intent": None,
            "action": "start_return" if ctx.offer is not None else result.action, "answer": result.reply,
            "would_have": plain({"offer": ctx.offer, "drafts": list(fake_drafts.rows.values()),
                                 "tasks": fake_snow.tasks, "cases": fake_snow.cases}),
            "state": chat.get("state"), "answered_at": datetime.now(UTC)}


def poll(client, store, answerer, since=None, sleep=time.sleep):
    """One tick. Returns {"stored", "closed", "errors", "clashes"}.

    New chats are those opened after the newest one stored (or `since` for an empty table). They are answered in
    order and the first failure ends the list: the watermark is the newest stored chat, so a chat after a failed
    one must not be stored first. A failure is logged and the same chat is tried again at the next tick.
    """
    done = {"stored": 0, "closed": 0, "errors": 0, "clashes": 0}
    mark = store.watermark() or since
    if mark is None:
        return done
    try:
        fresh = query(client, f"opened_at>{stamp(mark)}^ORDERBYopened_at", sleep)
    except ReadError as error:
        log.warning("could not read new chats: %s", error)
        done["errors"] += 1
        fresh = []
    for chat in fresh:
        try:
            if store.has(chat["number"]):
                # opened after everything we hold, yet the number is ours: the source reused a number. Say so; do not
                # answer it (a model call for a chat we would drop) and do not touch the stored one.
                log.warning("chat %s opened %s: number already stored (the newest stored chat is from %s); "
                            "the new chat is NOT stored", chat["number"], chat.get("opened_at"), stamp(mark))
                done["clashes"] += 1
                continue
            done["stored"] += store.save(shadow_answer(chat, answerer))
        except Exception:
            log.exception("chat %s failed; it will be tried again", chat.get("number"))
            done["errors"] += 1
            break
    for number in store.open_numbers():
        try:
            rows = query(client, f"number={number}", sleep)
            reply = agent_reply(rows[0]["transcript"]) if rows and rows[0].get("state") == "closed_complete" else None
            if reply is not None:
                done["closed"] += store.close(number, reply)
        except Exception:
            log.exception("could not check chat %s", number)
            done["errors"] += 1
    return done


def real_answerer(message, ctx):
    from agent import answer
    return answer(message, ctx)


def heartbeat():
    Path(os.environ.get("SHADOW_HEARTBEAT", "/tmp/shadow-heartbeat")).touch()


def start_mark():
    """Where an empty table starts: now, remembered in a file so `--once` runs and restarts agree on it."""
    path = Path(os.environ.get("SHADOW_START", "/tmp/shadow-start"))
    try:
        return parse_stamp(path.read_text().strip())
    except (OSError, ValueError):
        now = datetime.now(UTC).replace(microsecond=0)
        path.write_text(stamp(now))
        return now


def tick(store):
    done = poll(http_get, store, real_answerer, since=start_mark())
    heartbeat()
    print(f"stored {done['stored']}, closed {done['closed']}, errors {done['errors']}, clashes {done['clashes']}", flush=True)
    return done


def clip(text, width=100):
    text = " ".join((text or "-").split())
    return text if len(text) <= width else text[:width - 1] + "..."


def report(store, out=print):
    rows = store.last(20)
    out(f"{len(rows)} chats (newest first)")
    for r in rows:
        out(f"{r['number']}  {r['opened_at']:%Y-%m-%d %H:%M}  {r['action'] or '-'}")
        out(f"  message: {clip(r['message'])}")
        out(f"  answer:  {clip(r['answer'])}")
        out(f"  agent:   {clip(r['agent_reply'])}")


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    store = ShadowStore()
    store.create_tables()
    if "report" in argv:
        report(store)
        return 0
    if "--once" in argv:
        done = tick(store)
        return 1 if done["errors"] or done["clashes"] else 0
    every = float(os.environ.get("SHADOW_EVERY", "30"))
    while True:
        try:
            tick(store)
        except Exception:
            log.exception("tick failed; trying again in %ss", every)
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
