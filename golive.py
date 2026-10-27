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
import json
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

import config
import pilot

BUCKETS = 10_000
# The key of the hash. Changing it would reshuffle every visitor, so it is a constant, not a setting.
GROUP_KEY = b"demostore-golive-groups-v1"

ASSISTANT, CONTROL, PERSON = "assistant", "control", "person"
DEFAULTS = {"share": 0.05, "intents": ["order_status"], "on": False}  # off until someone switches it on

SETTING_FIELDS = ("share", "intents", "on", "changed_at")
CHAT_FIELDS = ("visitor_id", "chat_id", "group_name", "intent", "outcome", "handed_off", "input_tokens",
               "output_tokens", "cost", "simulated", "sim_day", "created_at", "rating", "repeat_contact",
               "confidently_wrong", "needs_person")
# Filled in after the chat, when its outcome is known (the simulation writes them; a real rating would come later).
OUTCOME_COLUMNS = (("rating", "smallint"), ("repeat_contact", "boolean"), ("confidently_wrong", "boolean"),
                   ("needs_person", "boolean"))


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
                created_at timestamptz NOT NULL,
                rating smallint CHECK (rating BETWEEN 1 AND 5), repeat_contact boolean, confidently_wrong boolean,
                needs_person boolean)""").format(c=c)
            ] + [sql.SQL("ALTER TABLE {c} ADD COLUMN IF NOT EXISTS {col} " + kind).format(c=c, col=sql.Identifier(col))
               for col, kind in OUTCOME_COLUMNS]


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

    def update_chat(self, chat_id, **fields):
        """Change the outcome columns of a chat as it goes on (a chat is one row, many turns). True if it was there."""
        fields = check_update(fields)
        if not fields:
            return False
        query = sql.SQL("UPDATE {t} SET {sets} WHERE chat_id = %(chat_id)s").format(
            t=self.chats_table, sets=sql.SQL(", ").join(
                sql.SQL("{} = {}").format(sql.Identifier(f), sql.Placeholder(f)) for f in fields))
        with self._connect() as conn:
            return conn.execute(query, {**fields, "chat_id": chat_id}).rowcount == 1

    def chats(self, simulated=None):
        """Every chat, oldest first (only the simulated or only the real ones if `simulated` is given)."""
        where = sql.SQL("") if simulated is None else sql.SQL("WHERE simulated = %s")
        with self._connect() as conn:
            cur = conn.execute(sql.SQL("SELECT {cols} FROM {t} {w} ORDER BY created_at, chat_id").format(
                cols=sql.SQL(", ").join(map(sql.Identifier, CHAT_FIELDS)), t=self.chats_table, w=where),
                () if simulated is None else (bool(simulated),))
            return [dict(zip(CHAT_FIELDS, r, strict=True)) for r in cur]


UPDATABLE = ("group_name", "intent", "outcome", "handed_off", "input_tokens", "output_tokens", "cost", "rating",
             "repeat_contact", "confidently_wrong", "needs_person")


def check_update(fields):
    """The columns a chat may change later; anything else (visitor, id, simulated, sim_day) is fixed at the start."""
    unknown = set(fields) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"a chat cannot change {sorted(unknown)}")
    if "group_name" in fields and fields["group_name"] not in (ASSISTANT, CONTROL, PERSON):
        raise ValueError("a chat needs a group: assistant, control or person")
    return {k: bool(v) if k == "handed_off" else v for k, v in fields.items()}


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

    def update_chat(self, chat_id, **fields):
        fields = check_update(fields)
        if chat_id not in self.rows or not fields:
            return False
        self.rows[chat_id].update(fields)
        return True


# ---- the numbers and the rollback lines ----------------------------------------------------------------------------
# Plain data in, plain data out, no model call. The margins live in sim_assumptions.json (signed by Lena); the tests pin them.

ASSUMPTIONS = Path(__file__).parent / "sim_assumptions.json"
RESOLVED_AS = ("resolved", "give_status", "start_return")
HANDED_AS = ("handed_off", "draft")
WEEK = 7
TWO_WEEKS = 14
NOT_ENOUGH = "not enough yet"
HOLDS, BREACH = "holds", "does not hold"


# The old ServiceNow chats (2,040) come from 15 customers, so "the same customer wrote again within 7 days" is true of
# nearly every chat (0.99), and "the same customer about the same order" of almost none (0.003): neither is a baseline.
REPEAT_NOT_MEASURED = "Not measured: the old chats come from 15 customers, so they give no repeat-contact baseline."


def margins(path=ASSUMPTIONS):
    with open(path) as f:
        return json.load(f)["margins"]


def day_of(chat):
    """The day a chat belongs to: its sim day, else the calendar day (as an ordinal, so days can be subtracted)."""
    return chat["sim_day"] if chat.get("sim_day") is not None else chat["created_at"].date().toordinal()


def classify(chat):
    """"resolved", "handed_off", "unanswered", or None for a control chat still waiting for its outcome (queued).
    An assistant chat that ended any other way is left without an answer."""
    outcome = chat.get("outcome")
    if outcome in RESOLVED_AS:
        return "resolved"
    if outcome in HANDED_AS or chat.get("handed_off"):
        return "handed_off"
    if outcome == "unanswered" or chat["group_name"] == ASSISTANT:
        return "unanswered"
    return None


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def group_numbers(chats):
    """One group's figures. `chats` counts every chat; the rates are over the chats whose outcome is known (`decided`)."""
    classes = [classify(c) for c in chats]
    decided = [(c, k) for c, k in zip(chats, classes, strict=True) if k]
    n = len(decided)
    count = {k: sum(1 for _, x in decided if x == k) for k in ("resolved", "handed_off", "unanswered")}
    ratings = [c["rating"] for c, _ in decided if c.get("rating") is not None]
    repeats = [c["repeat_contact"] for c, _ in decided if c.get("repeat_contact") is not None]
    model = [float(c["cost"]) for c, _ in decided if c.get("cost") is not None]
    reached = sum(1 for c, k in decided if k == "handed_off" or c["group_name"] == CONTROL)
    spend = sum(model) + reached * pilot.PERSON_COST
    return {"chats": len(chats), "decided": n, **count, "repeat_contacts": sum(map(bool, repeats)),
            "repeat_known": len(repeats), "rating_n": len(ratings), "rating": mean(ratings),
            "rating_values": ratings, "cost_total": spend if n else None, "cost_per_contact": pilot.rate(spend, n),
            "model_priced": len(model), "reached_person": reached,
            "confidently_wrong": sum(1 for c in chats if c.get("confidently_wrong")),
            "needs_person": sum(1 for c in chats if c.get("needs_person")),
            "needs_person_handed_off": sum(1 for c, k in decided if c.get("needs_person") and k == "handed_off")}


def diff_interval(good1, n1, good2, n2, z=pilot.Z95):
    """(difference p1 - p2, low, high): Newcombe's interval for two proportions, built from the two Wilson intervals."""
    p1, p2 = good1 / n1, good2 / n2
    (l1, u1), (l2, u2) = pilot.wilson(good1, n1, z), pilot.wilson(good2, n2, z)
    return (p1 - p2, p1 - p2 - ((p1 - l1) ** 2 + (u2 - p2) ** 2) ** 0.5, p1 - p2 + ((u1 - p1) ** 2 + (p2 - l2) ** 2) ** 0.5)


def mean_diff_interval(a, b, z=pilot.Z95):
    """(mean a - mean b, low, high) for two lists of ratings (normal approximation); None when either has fewer than 2."""
    if len(a) < 2 or len(b) < 2:
        return None
    def var(xs):
        m = mean(xs)
        return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    d = mean(a) - mean(b)
    half = z * (var(a) / len(a) + var(b) / len(b)) ** 0.5
    return d, d - half, d + half


def compare(assistant, control):
    """The assistant group against control: differences (assistant - control) with 95 % intervals and both sample sizes.

    `repeat` stays None: there is no control baseline to compare with (see REPEAT_NOT_MEASURED)."""
    out = {"n_assistant": assistant["decided"], "n_control": control["decided"], "resolved": None, "handed_off": None,
           "unanswered": None, "repeat": None, "rating": None, "cost_per_contact": None}
    if assistant["decided"] and control["decided"]:
        for key in ("resolved", "handed_off", "unanswered"):
            out[key] = diff_interval(assistant[key], assistant["decided"], control[key], control["decided"])
        if assistant["cost_per_contact"] is not None and control["cost_per_contact"] is not None:
            out["cost_per_contact"] = assistant["cost_per_contact"] - control["cost_per_contact"]
    out["rating"] = mean_diff_interval(assistant["rating_values"], control["rating_values"])
    return out


def window_numbers(chats):
    """The two groups, and the difference, over the chats given. `person` chats (switch off or intent not live) are
    only counted, never compared."""
    groups = {g: [c for c in chats if c["group_name"] == g] for g in (ASSISTANT, CONTROL, PERSON)}
    assistant, control = group_numbers(groups[ASSISTANT]), group_numbers(groups[CONTROL])
    return {"total": len(chats), "person": len(groups[PERSON]), ASSISTANT: assistant, CONTROL: control,
            "difference": compare(assistant, control)}


def numbers(store, now):
    """Everything the page shows for the go-live, as plain data. `now` is only stamped on the result.

    The "day" is the latest day with chats (its sample is what the alert looks at); the "week" is that day and the six
    before it; "window" is the two weeks the decision is made on. Each is the same `window_numbers`."""
    chats = store.chats()
    last = max((day_of(c) for c in chats), default=None)
    days = sorted({day_of(c) for c in chats})

    def within(first):
        return [c for c in chats if first <= day_of(c) <= last] if chats else []

    return {"as_of": now, "repeat_note": REPEAT_NOT_MEASURED, "total": len(chats), "simulated": sum(1 for c in chats if c.get("simulated")),
            "last_day": last, "days_with_chats": len(days),
            "day": window_numbers([c for c in chats if day_of(c) == last]),
            "week": window_numbers(within(last - WEEK + 1) if chats else []),
            "window": window_numbers(within(last - TWO_WEEKS + 1) if chats else []),
            "by_day": {d: window_numbers([c for c in chats if day_of(c) == d]) for d in days},
            "margins": margins()}


def _line(name, limit, value, n, status, interval=None, detail=""):
    return {"name": name, "limit": limit, "value": value, "n": n, "status": status, "interval": interval, "detail": detail}


def _status(value, limit, worse_is_higher=True):
    gap = round(value - limit, 9)  # the limit itself holds; rounding keeps 0.13 - 0.10 <= 0.03 from failing on float noise
    return HOLDS if (gap <= 0 if worse_is_higher else gap >= 0) else BREACH


def wrong_line(group, limit):
    n = group["chats"]
    if not n:
        return _line("confidently wrong", limit, None, 0, NOT_ENOUGH)
    rate = group["confidently_wrong"] / n
    return _line("confidently wrong", limit, rate, n, _status(rate, limit), pilot.wilson(group["confidently_wrong"], n),
                 f"{group['confidently_wrong']} of {n} assistant chats")


def hand_off_line(group, limit):
    n = group["needs_person"]
    if not n:
        return _line("hand-off when a person is needed", limit, None, 0, NOT_ENOUGH)
    rate = group["needs_person_handed_off"] / n
    return _line("hand-off when a person is needed", limit, rate, n, _status(rate, limit, worse_is_higher=False),
                 pilot.wilson(group["needs_person_handed_off"], n),
                 f"{group['needs_person_handed_off']} of {n} chats that need a person")


def unanswered_line(window, limit):
    d = window["difference"]["unanswered"]
    if d is None:
        return _line("left without an answer, against control", limit, None, 0, NOT_ENOUGH)
    n = (window["difference"]["n_assistant"], window["difference"]["n_control"])
    return _line("left without an answer, against control", limit, d[0], n, _status(d[0], limit), (d[1], d[2]),
                 "percentage points worse than control (1.0 = 100 points)")


def rating_line(window, limit):
    d = window["difference"]["rating"]
    n = (window["assistant"]["rating_n"], window["control"]["rating_n"])
    if d is None:
        return _line("rating, against control", limit, None, n, NOT_ENOUGH)
    return _line("rating, against control", limit, -d[0], n, _status(-d[0], limit), (-d[2], -d[1]),
                 "points lower than control on the 1-5 scale")


def lines(data):
    """The rollback lines on `numbers(...)`: the confidently-wrong line on the day (the alert) and over the week, and the
    other three over the week. Each is {name, limit, value, n, status, interval, detail}, status "holds",
    "does not hold" or "not enough yet" - a group with no chats is never a division error.

    "two_weeks" is the go-live check: 14 days of chats and all four lines hold over those 14 days. A day's alert is
    listed in `alert_days` but does not decide it: a day of about 10 chats cannot measure 1 in 100, and the drill
    exists to answer an alert on the day."""
    m = data["margins"]
    week, window, day = data["week"], data["window"], data["day"]

    def four(w):
        return {"confidently_wrong": wrong_line(w[ASSISTANT], m["confidently_wrong"]),
                "hand_off": hand_off_line(w[ASSISTANT], m["hand_off_min"]),
                "unanswered": unanswered_line(w, m["unanswered_points"]),
                "rating": rating_line(w, m["rating"])}

    two = four(window)
    statuses = [x["status"] for x in two.values()]
    if data["days_with_chats"] < TWO_WEEKS or NOT_ENOUGH in statuses:
        verdict = NOT_ENOUGH
    else:
        verdict = HOLDS if all(s == HOLDS for s in statuses) else BREACH
    alert = wrong_line(day[ASSISTANT], m["confidently_wrong"])
    return {"day": {"confidently_wrong": alert, "alert": alert["status"] == BREACH}, "week": four(week), "window": two,
            "alert_days": [d for d, w in data["by_day"].items()
                           if wrong_line(w[ASSISTANT], m["confidently_wrong"])["status"] == BREACH],
            "two_weeks": {"status": verdict, "days": data["days_with_chats"], "needed": TWO_WEEKS}}
