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
import hashlib
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
import handoff
import refunds
import servicenow
import traces
from intent import handoff_reason
from masking import mask_cards

log = logging.getLogger("shadow")

CHATS = "/api/now/table/interaction"
PAGE = 100
TIMEOUT = 10
RETRIES = 3  # tries for one call that gets 429

# The columns, in order. Only the chat and what we made of it: no session id, no hash, no other customer data.
FIELDS = ("number", "opened_at", "opened_for", "market", "message", "intent", "action", "answer",
          "would_have", "state", "agent_reply", "answered_at", "input_tokens", "output_tokens")


def tables(name="shadow_chats"):
    """The CREATE statement; the name is a parameter so a live test can use its own table."""
    return [sql.SQL("""CREATE TABLE IF NOT EXISTS {t} (
        number text PRIMARY KEY, opened_at timestamptz NOT NULL, opened_for text NOT NULL, market text,
        message text NOT NULL, intent text, action text, answer text,
        would_have jsonb NOT NULL DEFAULT '{{}}'::jsonb, state text,
        agent_reply text, answered_at timestamptz NOT NULL)""").format(t=sql.Identifier(name)),
            # additive: rows from before the tokens were stored keep NULL ("unpriced" on the pilot page)
            *[sql.SQL("ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} int").format(t=sql.Identifier(name), c=sql.Identifier(c))
              for c in ("input_tokens", "output_tokens")]]


VERDICTS = ("same", "better", "worse", "wrong")
MARK_FIELDS = ("number", "marker", "marked_at", "verdict", "sounded_sure")


def marks_tables(name="shadow_marks"):
    """The CREATE for the marks: one per (chat, person); `sounded_sure` only goes with `wrong`."""
    return [sql.SQL("""CREATE TABLE IF NOT EXISTS {t} (
        number text NOT NULL, marker text NOT NULL, marked_at timestamptz NOT NULL,
        verdict text NOT NULL CHECK (verdict IN ('same', 'better', 'worse', 'wrong')),
        sounded_sure boolean NOT NULL DEFAULT false,
        PRIMARY KEY (number, marker),
        CHECK (verdict = 'wrong' OR NOT sounded_sure))""").format(t=sql.Identifier(name))]


def check_mark(marker, verdict, sounded_sure):
    """The name stripped; ValueError for an empty name, an unknown verdict, or `sounded_sure` without `wrong`."""
    marker = (marker or "").strip()
    if not marker:
        raise ValueError("a mark needs the name of the person who made it")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
    if sounded_sure and verdict != "wrong":
        raise ValueError("sounded_sure goes only with the verdict wrong")
    return marker


def sample_key(number, day):
    """Random across days, stable within one: the same ordering the SQL gets from md5(number || day)."""
    return hashlib.md5(f"{number}{day.isoformat()}".encode()).hexdigest()


class ShadowStore:
    """The real table in the `product` database."""

    def __init__(self, url=None, table="shadow_chats", marks_table="shadow_marks", **connect_args):
        self.url = url or config.store_url()
        self.name = table
        self.table = sql.Identifier(table)
        self.marks_name = marks_table
        self.marks_table = sql.Identifier(marks_table)
        self.connect_args = connect_args

    def _connect(self):
        return psycopg.connect(self.url, **self.connect_args)

    def create_tables(self):
        with self._connect() as conn:
            for statement in [*tables(self.name), *marks_tables(self.marks_name)]:
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

    def all(self):
        """Every stored chat, oldest first, as dicts."""
        with self._connect() as conn:
            cur = conn.execute(sql.SQL("SELECT {cols} FROM {t} ORDER BY opened_at, number").format(
                cols=sql.SQL(", ").join(map(sql.Identifier, FIELDS)), t=self.table))
            return [dict(zip(FIELDS, r, strict=True)) for r in cur]

    def mark(self, number, marker, verdict, sounded_sure=False, now=None):
        """A person's verdict on a chat; marking again replaces it and moves `marked_at`. ValueError if rejected."""
        marker = check_mark(marker, verdict, sounded_sure)
        query = sql.SQL("""INSERT INTO {m} (number, marker, marked_at, verdict, sounded_sure)
            SELECT number, %s, %s, %s, %s FROM {t} WHERE number = %s
            ON CONFLICT (number, marker) DO UPDATE
            SET marked_at = EXCLUDED.marked_at, verdict = EXCLUDED.verdict, sounded_sure = EXCLUDED.sounded_sure""").format(
            m=self.marks_table, t=self.table)
        with self._connect() as conn:
            if conn.execute(query, (marker, now or datetime.now(UTC), verdict, bool(sounded_sure), number)).rowcount != 1:
                raise ValueError(f"no chat {number}")

    def marks(self, number=None):
        """All marks (of one chat if given), oldest first, as dicts."""
        where = sql.SQL("WHERE number = %s") if number is not None else sql.SQL("")
        with self._connect() as conn:
            cur = conn.execute(sql.SQL("SELECT {cols} FROM {m} {w} ORDER BY marked_at, number, marker").format(
                cols=sql.SQL(", ").join(map(sql.Identifier, MARK_FIELDS)), m=self.marks_table, w=where),
                (number,) if number is not None else ())
            return [dict(zip(MARK_FIELDS, r, strict=True)) for r in cur]

    def delete_before(self, cutoff):
        """Delete the chats opened before `cutoff` and the marks of those chats; return the number of chats."""
        with self._connect() as conn:
            conn.execute(sql.SQL("DELETE FROM {m} WHERE number IN (SELECT number FROM {t} WHERE opened_at < %s)").format(
                m=self.marks_table, t=self.table), (cutoff,))
            return conn.execute(sql.SQL("DELETE FROM {t} WHERE opened_at < %s").format(t=self.table), (cutoff,)).rowcount

    def sample(self, n, day):
        """Up to n unmarked chats that have an agent reply, in the order of md5(number || day)."""
        with self._connect() as conn:
            cur = conn.execute(sql.SQL("""SELECT {cols} FROM {t} c
                WHERE c.agent_reply IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM {m} k WHERE k.number = c.number)
                ORDER BY md5(c.number || %s), c.number LIMIT %s""").format(
                cols=sql.SQL(", ").join(sql.SQL("c.") + sql.Identifier(f) for f in FIELDS),
                t=self.table, m=self.marks_table), (day.isoformat(), n))
            return [dict(zip(FIELDS, r, strict=True)) for r in cur]


class FakeShadowStore:
    """The same interface in memory."""

    def __init__(self):
        self.rows = {}
        self.mark_rows = {}  # (number, marker) -> mark

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

    def all(self):
        return [dict(r) for r in sorted(self.rows.values(), key=lambda r: (r["opened_at"], r["number"]))]

    def mark(self, number, marker, verdict, sounded_sure=False, now=None):
        marker = check_mark(marker, verdict, sounded_sure)
        if number not in self.rows:
            raise ValueError(f"no chat {number}")
        self.mark_rows[(number, marker)] = {"number": number, "marker": marker, "marked_at": now or datetime.now(UTC),
                                            "verdict": verdict, "sounded_sure": bool(sounded_sure)}

    def marks(self, number=None):
        found = [dict(m) for m in self.mark_rows.values() if number is None or m["number"] == number]
        return sorted(found, key=lambda m: (m["marked_at"], m["number"], m["marker"]))

    def delete_before(self, cutoff):
        gone = {n for n, r in self.rows.items() if r["opened_at"] < cutoff}
        self.rows = {n: r for n, r in self.rows.items() if n not in gone}
        self.mark_rows = {k: m for k, m in self.mark_rows.items() if k[0] not in gone}
        return len(gone)

    def sample(self, n, day):
        marked = {m["number"] for m in self.mark_rows.values()}
        pool = [r for r in self.rows.values() if r["agent_reply"] is not None and r["number"] not in marked]
        return [dict(r) for r in sorted(pool, key=lambda r: (sample_key(r["number"], day), r["number"]))[:n]]


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


def real_classifier(message):
    from intent import classify
    return classify(message)


def shadow_answer(chat, answerer, classifier=None):
    """Answer one live chat as its verified customer; return the row to store. Everything it would write goes to fakes.

    Same gate as the chat service: classify, then `handoff_reason`; a hand-off opens the case against the fake
    ServiceNow and `answerer` is not called. Card numbers are masked before the model sees them and before storing.
    """
    fake_drafts, fake_snow, fake_traces = drafts.FakeDrafts(), servicenow.FakeServiceNow(), traces.FakeTraces()
    traces.set_sink(fake_traces)  # first of all, so no model call of this chat reaches the real trace table
    refunds.set_systems(None, fake_drafts, fake_snow)  # Ledgerline stays the read-only copy
    number = chat["number"]
    message = mask_cards(customer_message(chat.get("transcript", "")))
    ctx = refunds.Context(chat["opened_for"], f"shadow-{number}", market=chat.get("u_market") or None)
    token = traces.current_session.set(ctx.session_id)
    try:
        intent = (classifier or real_classifier)(message)
        reason = handoff_reason(intent)
        if reason:
            reply = handoff.open_case(ctx, intent["summary"], [{"role": "user", "content": message}],
                                      reason, reason.replace("_", " "))
            action = "hand_off"
        else:
            result = answerer(message, ctx)
            reply = result.reply
            action = "start_return" if ctx.offer is not None else result.action
    finally:
        traces.current_session.reset(token)
    calls = fake_traces.rows
    return {"number": number, "opened_at": parse_stamp(chat["opened_at"]), "opened_for": chat["opened_for"],
            "market": chat.get("u_market") or None, "message": message, "intent": intent["intent"],
            "action": action, "answer": mask_cards(reply),
            "would_have": plain({"offer": ctx.offer, "drafts": list(fake_drafts.rows.values()),
                                 "tasks": fake_snow.tasks, "cases": fake_snow.cases}),
            "state": chat.get("state"), "answered_at": datetime.now(UTC),
            "input_tokens": sum(r["input_tokens"] for r in calls) if calls else None,
            "output_tokens": sum(r["output_tokens"] for r in calls) if calls else None}


def poll(client, store, answerer, since=None, sleep=time.sleep, classifier=None):
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
            done["stored"] += store.save(shadow_answer(chat, answerer, classifier))
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
