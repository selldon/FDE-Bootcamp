"""SIMULATED customers for the go-live: seeded visitors for 14 days, written to the running chat service.

    python golive_sim.py --dry-run                 the plan (visitors, groups, model calls, cost); writes nothing, calls nothing
    python golive_sim.py --days 1-7                run sim days 1..7 against the service (live: assistant visitors call Claude)
    python golive_sim.py --refresh-repeat          compute the control group's repeat-contact rate from the old ServiceNow chats
    python golive_sim.py --rescore                 score the stored chats again from the replies in `traces` (no model call)
    python golive_sim.py --drill-day 15            the night with no carrier file (live; --dry-run shows the plan); 15, then 16
    python golive_sim.py --write-drill-night       write the hidden carrier file of the 23rd (the world moved on; never on the SFTP)
    python golive_sim.py --replay-drill 15         the drill day's chats again, in this process, on today's code (live model;
                                                   writes no row and reaches no real system)

Each visitor has an id, a day, a question and (for "where is my order") 1-3 follow-ups, taken from the profiles in
`data/` and the sandbox's hard profiles. The simulation knows the true status of every order. Only the assistant
group's turns reach Claude (through `/chat` and `llm.py`); the control group sends its first message to the live queue and
its outcome is drawn from `sim_assumptions.json`. Every row written carries `"simulated": true`.

At most `assistant_cap` assistant conversations in all: a day that would pass the cap is not run, and the runner says so.
"""
import argparse
import csv
import json
import random
import re
import shutil
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import carrier
import golive
import llm
import pilot
from golive import ASSISTANT, CONTROL

HERE = Path(__file__).parent
ASSUMPTIONS = HERE / "sim_assumptions.json"
OUT = HERE / "data" / "golive_sim.jsonl"
CARRIER_FOLDER = HERE / "sandbox" / "systems" / "carrier" / "upload"  # the carrier's nightly files, as on its SFTP server
DRILL_FILE = HERE / "sandbox" / "systems" / "carrier" / "drill" / "carrier-2026-10-23.csv"  # beside upload/, never served
SHARE = 0.05
ORDER_STATUS = "order_status"
RESOLVED_OUTCOMES = ("give_status", "start_return")


def load_assumptions(path=ASSUMPTIONS):
    with open(path) as f:
        return json.load(f)


# ---- the truth: what is really the matter with each order ---------------------------------------------------------

FAMILY = {"delivered": "delivered", "shipped": "on_the_way", "in transit": "on_the_way",
          "out for delivery": "on_the_way", "processing": "processing", "partly shipped": "partly"}


def build_truth(orders, carrier):
    """{order number: {status, dates}} for the simulated world. `carrier` is the carrier's rows (tracking, status, date):
    a parcel's own news wins over the order's status, and the dates that count as true are the promised date and the
    dates of the carrier's news. Phase 7 hands this a carrier file with a night missing."""
    news = {r["tracking"]: r for r in carrier}
    truth = {}
    for o in orders:
        parcels = [news[t] for t in o["tracking"] if t in news]
        if o["status"] == "partly shipped":
            status = "partly"
        elif parcels and len(parcels) == len(o["tracking"]):
            status = "delivered" if all(p["status"] == "delivered" for p in parcels) else "on_the_way"
        else:
            status = FAMILY.get(o["status"], o["status"])
        dates = {o["promised"], *(p["date"] for p in parcels)} - {None, ""}
        everything_delivered = len(parcels) == len(o["tracking"]) and all(p["status"] == "delivered" for p in parcels)
        truth[o["number"]] = {"status": status, "dates": sorted(dates), "customer": o["customer"],
                              "all_delivered": bool(parcels) and everything_delivered}
    return truth


def newest_carrier(folder=CARRIER_FOLDER):
    """(file name, rows) of the carrier's newest night, the file the service loads, with the dates as ISO strings.

    The truth must come from the same night the service reads: the repo's `data/carrier.csv` is the night of the 21st, one
    night behind the service on the morning of the 22nd, and every correct answer about that night was scored wrong."""
    names = sorted(p.name for p in Path(folder).glob("carrier-*.csv") if carrier.NAME.match(p.name))
    if not names:
        raise SystemExit(f"no carrier file in {folder}: the truth cannot be built")
    rows = carrier.parse((Path(folder) / names[-1]).read_bytes(), names[-1])
    return names[-1], [{**r, "date": r["date"].isoformat()} for r in rows]


def load_truth(orders_path=HERE / "data" / "orders.json", carrier_folder=CARRIER_FOLDER):
    with open(orders_path) as f:
        orders = json.load(f)
    _, rows = newest_carrier(carrier_folder)
    return orders, build_truth(orders, rows)


# ---- scoring: a status given as fact that differs from the truth, counted by code ------------------------------------

STATUS_CLAIMS = {
    "delivered": re.compile(r"\b(?:has been|have been|was|were|is|shows|marked as|status:?)\s+delivered\b"
                            r"|(?<!be )\bdelivered\s+(?:on|at)\b", re.IGNORECASE),
    "on_the_way": re.compile(r"\b(?:in transit|on its way|on the way|with the carrier|out for delivery"
                             r"|(?:has|was|is|been)\s+shipped)\b", re.IGNORECASE),
    "processing": re.compile(r"\b(?:is|still|currently)\s+(?:being\s+)?processing\b|\bstatus:?\s+processing\b", re.IGNORECASE),
    "partly": re.compile(r"\bpartly shipped\b|\bpart of your order\b", re.IGNORECASE),
}
# A claim that follows a negation within a few words ("isn't still on its way", "not in transit", "no longer on the way")
# says the opposite. Only a negation just before the phrase counts, so "I can't find a scan, but it is on its way" is
# still a claim.
NEGATED = re.compile(r"(?:\b(?:not|never|no longer|cannot)|n['\u2019]t)\s+(?:\w+\s+){0,3}$", re.IGNORECASE)
# A reply that says the news is old is not a status given as fact.
HEDGE = re.compile(r"\b(?:old|out of date|outdated|stale|cannot confirm|can't confirm|not sure|may have changed"
                   r"|might have changed|not up to date|no recent)\b", re.IGNORECASE)
# A partly shipped order whose parcels are all delivered: "delivered" is right if the reply names the part-shipped status.
PARTLY_NAMED = re.compile(r"\bpart(?:ly|ially)?[\s-]+shipped\b|\bpartly\b|\bpartially\b", re.IGNORECASE)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"], 1)}
# whole month words or their usual short forms - never a prefix: "Nova 32" is a monitor, not "Nov 32"
_MON = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?"
        r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}\b(?:,?\s+(\d{{4}}))?", re.IGNORECASE)
MONTH_DAY = re.compile(rf"\b{_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", re.IGNORECASE)


def dates_in(text, year):
    """Every date the text states, as ISO strings; a date without a year gets `year`."""
    found = {f"{y}-{m}-{d}" for y, m, d in ISO_DATE.findall(text)}
    for d, mon, y in DAY_MONTH.findall(text):
        found.add(f"{y or year}-{MONTHS[mon.lower()[:3]]:02d}-{int(d):02d}")
    for mon, d, y in MONTH_DAY.findall(text):
        found.add(f"{y or year}-{MONTHS[mon.lower()[:3]]:02d}-{int(d):02d}")
    return found


def score_reply(reply, truth):
    """Is this reply a status given as fact that differs from the truth (its status or its date)? Plain data back."""
    if truth is None or HEDGE.search(reply):
        return {"wrong": False, "status_wrong": False, "date_wrong": False, "claims": []}
    claims = [k for k, rx in STATUS_CLAIMS.items() if any(not NEGATED.search(reply[:m.start()]) for m in rx.finditer(reply))]
    allowed = {truth["status"]} | ({"on_the_way", "processing"} if truth["status"] == "partly" else set())
    if truth["status"] == "partly" and truth.get("all_delivered") and PARTLY_NAMED.search(reply):
        allowed.add("delivered")  # every parcel is delivered and the reply says the order still reads part shipped
    year = (truth["dates"][0] if truth["dates"] else "2026")[:4]
    stated = dates_in(reply, year)
    status_wrong = bool(claims) and not set(claims) <= allowed
    date_wrong = bool(stated) and not stated <= set(truth["dates"])
    return {"wrong": status_wrong or date_wrong, "status_wrong": status_wrong, "date_wrong": date_wrong,
            "claims": claims}


# ---- the visitors --------------------------------------------------------------------------------------------------

@dataclass
class Visitor:
    id: str
    day: int
    group: str
    intent: str
    customer: str
    order: str | None
    messages: list
    needs_person: bool
    kind: str
    turns: int = field(init=False)

    def __post_init__(self):
        self.turns = len(self.messages)


FIRST = ["Hi, where is my order {order}? It was due on {weekday}.", "Can you tell me the status of order {order}?",
         "My order {order} has not arrived yet. Where is it?"]
FOLLOW = ["Thanks. When exactly will it arrive?", "Is there a tracking update?", "Has it left the warehouse?",
          "Ok, and is that the latest information?"]
ASK_PERSON = "Can I talk to a person, please?"
OTHER_INTENT = {
    "policy_question": ["How long do I have to return a laptop?", "What is your warranty on a monitor?"],
    "return_request": ["I want to return the {item} from order {order}. It is too loud."],
    "other": ["Hello, I have a question about my account."],
}
HARD = {  # first message, follow-ups
    "angry": ("WHERE IS MY ORDER {order}. I NEED IT NOW.", ["This shop is a joke. Where is it?", "I want a person. Now."]),
    "confused": ("I think my order is {wrong}, where is it?", ["Sorry, the number is {order}.", "Why is it taking so long?"]),
    "manager": ("Where is order {order}? I want to speak to your manager.", ["Get me your manager."]),
    "topic": ("Where is {order}? Also, do you sell phones?", ["What about the status of the order?"]),
    "other": ("I need to change the delivery address of {order}.", ["Can you do it now?"]),
}


def load_profiles(path=HERE / "sandbox" / "data" / "hard_profiles.json"):
    with open(path) as f:
        return json.load(f)


def make_visitors(day, assumptions, orders, profiles, share=SHARE, seed=None):
    """The visitors of one sim day: the same seed and day always give the same list."""
    seed = assumptions["seed"] if seed is None else seed
    rng = random.Random(f"{seed}-{day}")
    n = round(assumptions["visitors_per_day"] * rng.uniform(0.9, 1.1))
    intents, weights = zip(*assumptions["intent_mix"].items(), strict=True)
    low, high = assumptions["followups"]
    visitors = []
    for i in range(n):
        vid = f"sim-{seed}-d{day:02d}-{i:04d}"
        intent = rng.choices(intents, weights)[0]
        order = rng.choice(orders)
        group = golive.group_of(vid, share)
        kind, needs_person = "plain", False
        if intent != ORDER_STATUS:
            text = rng.choice(OTHER_INTENT[intent]).format(item=order["items"][0], order=order["number"])
            visitors.append(Visitor(vid, day, group, intent, order["customer"], order["number"], [text], False, kind))
            continue
        if rng.random() < assumptions["hard_profile_share"]:
            p = rng.choice(profiles)
            kind = p["id"].split("-")[1]  # angry, confused, manager, topic, other (from "other-order")
            order = next((o for o in orders if o["number"] == p["expect"]["order"]), order)  # no order: any order
            wrong = next((n for n in re.findall(r"DS-\d+", p["profile"]["knows"]) if n != order["number"]), "DS-00000")
            first, more = HARD[kind]
            fill = {"order": order["number"], "wrong": wrong}
            messages = [first.format(**fill)] + [m.format(**fill) for m in more]
            needs_person = bool(p["expect"]["person"])
        else:
            messages = [rng.choice(FIRST).format(order=order["number"], weekday=rng.choice(["Monday", "Friday"]))]
            messages += rng.sample(FOLLOW, rng.randint(low, high))
            if rng.random() < assumptions["ask_person_share"]:
                messages[-1] = ASK_PERSON
                needs_person = True
        visitors.append(Visitor(vid, day, group, intent, order["customer"], order["number"], messages, needs_person,
                                kind))
    return visitors


# ---- the plan ------------------------------------------------------------------------------------------------------

def calls_for(visitor, estimate):
    """Expected model calls of an assistant conversation: a message that is not live costs one classification."""
    return estimate["calls_per_turn"] * visitor.turns if visitor.intent == ORDER_STATUS else 1


def plan(assumptions, days, share=SHARE, already=0, orders=None, profiles=None, seed=None):
    """What a run would do, without doing it. A day that would pass the cap is not run (`stopped_on`)."""
    if orders is None:
        orders, _ = load_truth()
    profiles = load_profiles() if profiles is None else profiles
    cap, est = assumptions["assistant_cap"], assumptions["estimate"]
    price_in, price_out = llm.PRICES[llm.MODEL]
    out = {"visitors": 0, "control": 0, "assistant": 0, "calls": 0, "days": [], "stopped_on": None, "cap": cap}
    used = already
    for day in days:
        vs = make_visitors(day, assumptions, orders, profiles, share, seed)
        mine = [v for v in vs if v.group == ASSISTANT]
        if used + len(mine) > cap:
            out["stopped_on"] = day
            break
        used += len(mine)
        out["visitors"] += len(vs)
        out["assistant"] += len(mine)
        out["control"] += len(vs) - len(mine)
        out["calls"] += sum(calls_for(v, est) for v in mine)
        out["days"].append({"day": day, "visitors": len(vs), "assistant": len(mine)})
    tokens_in, tokens_out = out["calls"] * est["input_tokens_per_call"], out["calls"] * est["output_tokens_per_call"]
    out["cost"] = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
    out["model"] = llm.MODEL
    return out


def describe(p):
    lines = [f"SIMULATED traffic - plan for {len(p['days'])} day(s)",
             f"visitors: {p['visitors']} (control {p['control']}, assistant {p['assistant']})",
             f"assistant conversations: {p['assistant']} of at most {p['cap']}",
             f"expected model calls: {p['calls']} ({p['model']})",
             f"cost estimate: ${p['cost']:.2f} (from llm.PRICES and the token estimates in sim_assumptions.json)"]
    if p["stopped_on"]:
        lines.append(f"STOPPED: day {p['stopped_on']} would pass the cap of {p['cap']} assistant conversations; "
                     f"that day and the ones after it are not run")
    return "\n".join(lines)


# ---- the outcomes the rules give -----------------------------------------------------------------------------------

def draw(rng, weights):
    return rng.choices([1, 2, 3, 4, 5], weights)[0]


def control_outcome(visitor, assumptions, rng):
    rules = assumptions["control"][visitor.intent]
    cls = rng.choices(["resolved", "handed_off", "unanswered"],
                      [rules["resolved"], rules["handed_off"], rules["unanswered"]])[0]
    return cls, draw(rng, rules["rating"])


def assistant_outcome(row, wrong, assumptions, rng):
    """resolved / handed_off / unanswered from the stored row of the chat; a wrong status rates on its own rule."""
    if row is None:
        cls = "unanswered"
    elif row["outcome"] in RESOLVED_OUTCOMES:
        cls = "resolved"
    elif row["handed_off"] or row["outcome"] in ("handed_off", "draft"):
        cls = "handed_off"
    else:
        cls = "unanswered"
    rule = "wrong" if wrong else cls
    return cls, draw(rng, assumptions["assistant_rating"][rule])


def repeat_contact(cls, wrong, group, assumptions, rng):
    base = assumptions["control_repeat_rate"]
    factor = assumptions["assistant_repeat_factor"]["wrong" if wrong else cls] if group == ASSISTANT else 1.0
    return rng.random() < min(1.0, base * factor)


def repeat_rate(old_chats, window_days=7):
    """(share of old chats whose customer wrote again within the window, number of chats)."""
    by_customer = {}
    for c in old_chats:
        by_customer.setdefault(c["opened_for"], []).append(datetime.strptime(c["opened_at"], "%Y-%m-%d %H:%M:%S"))
    repeats = 0
    for times in by_customer.values():
        times.sort()
        repeats += sum(1 for i, t in enumerate(times) if i + 1 < len(times) and times[i + 1] - t <= timedelta(
            days=window_days))
    total = sum(len(t) for t in by_customer.values())
    return (repeats / total if total else None), total


# ---- talking to the service ----------------------------------------------------------------------------------------

class HttpGateway:
    """The running chat service over HTTP. The one-time code is read from the service's outbox file, as the customer
    would read it in their email."""

    def __init__(self, url, outbox="data/outbox.jsonl"):
        self.url, self.outbox = url.rstrip("/"), Path(outbox)

    def post(self, path, body):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    def chat(self, body):
        return self.post("/chat", body)

    def verify(self, email):
        """A session whose customer is verified."""
        sid = self.post("/verify/start", {"email": email})["session_id"]
        code = self.code_for(email)
        self.post("/verify/check", {"session_id": sid, "email": email, "code": code})
        return sid

    def code_for(self, email):
        lines = [json.loads(line) for line in self.outbox.read_text().splitlines() if line.strip()]
        return next(row["code"] for row in reversed(lines) if row["to"] == email)


def run_visitor(visitor, gateway):
    """Send the visitor's script. Returns (session id, the assistant's replies)."""
    base = {"visitor_id": visitor.id, "simulated": True, "sim_day": visitor.day}
    if visitor.group == CONTROL:  # a person answers; only the first message is sent to the queue
        return gateway.chat({"message": visitor.messages[0], **base})["session_id"], []
    sid = gateway.verify(visitor.customer) if visitor.intent == ORDER_STATUS else None
    replies = []
    for message in visitor.messages:
        out = gateway.chat({"message": message, "session_id": sid, **base})
        sid = out["session_id"]
        replies.append(out["reply"])
    return sid, replies


def run_day(day, visitors, gateway, store, truth, assumptions, seed):
    """One sim day against the service. Returns the rows of the day (all `simulated: true`)."""
    sessions = [(v, *run_visitor(v, gateway)) for v in visitors]
    return outcome_rows(day, sessions, store, truth, assumptions, seed)


def outcome_rows(day, sessions, store, truth, assumptions, seed):
    """The labelled rows of a day from its sessions: (visitor, chat id, the replies the customer was given)."""
    stored = {r["chat_id"]: r for r in store.chats(simulated=True)}
    rows = []
    for v, sid, replies in sessions:
        rng = random.Random(f"{seed}-{day}-{v.id}-outcome")
        scores = [score_reply(r, truth.get(v.order)) for r in replies] if v.intent == ORDER_STATUS else []
        wrong = any(s["wrong"] for s in scores)
        if v.group == CONTROL:
            cls, rating = control_outcome(v, assumptions, rng)
            model_cost, person_cost = None, pilot.PERSON_COST
        else:
            row = stored.get(sid)
            cls, rating = assistant_outcome(row, wrong, assumptions, rng)
            model_cost = float(row["cost"]) if row and row["cost"] is not None else None
            person_cost = pilot.PERSON_COST if cls == "handed_off" else 0.0
        rows.append({
            "simulated": True, "seed": seed, "sim_day": day, "visitor_id": v.id, "chat_id": sid, "group": v.group,
            "intent": v.intent, "kind": v.kind, "order": v.order, "turns": v.turns, "needs_person": v.needs_person,
            "true_status": (truth.get(v.order) or {}).get("status"), "true_dates": (truth.get(v.order) or {}).get("dates"),
            "outcome": cls, "reached_person": cls == "handed_off" or v.group == CONTROL,
            "confidently_wrong": wrong, "claims": sorted({c for s in scores for c in s["claims"]}),
            "rating": rating, "repeat_contact": repeat_contact(cls, wrong, v.group, assumptions, rng),
            "model_cost": model_cost, "person_cost": person_cost, "last_reply": replies[-1] if replies else None})
    return rows


def read_out(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_out(path, rows):
    """Add rows; the file is only ever appended to."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.writelines(json.dumps(row) + "\n" for row in rows)


def write_labels(store, rows):
    """Put each chat's labels in the service table, which is what the page reads: without them every line is empty.

    A control chat's outcome replaces "queued" (the rule's outcome); an assistant chat keeps the outcome the service
    wrote. `repeat_contact` is not written: repeat contact is not measured (the old chats are 15 customers), so the
    table holds no number for it. Returns how many chats the table did not have."""
    lost = 0
    for r in rows:
        fields = {"rating": r["rating"], "confidently_wrong": r["confidently_wrong"], "needs_person": r["needs_person"]}
        if r["group"] == CONTROL:
            fields["outcome"] = r["outcome"]
        if not store.update_chat(r["chat_id"], **fields):
            lost += 1
    return lost


def rescore(assumptions, store, truth, replies_of, out, orders, profiles, share=SHARE):
    """Score the stored chats again from the replies the customers were given (`replies_of(chat id)`), no model call,
    and put the labels in the table. Returns the new rows; `replace_out` writes them.

    A chat that should have replies and has none is not scored as right: nothing was measured, so it stops."""
    old = read_out(out)
    if not old:
        raise SystemExit(f"{out} has no rows to rescore")
    chat_of = {(r["sim_day"], r["visitor_id"]): r["chat_id"] for r in old}
    stored = {c["chat_id"]: c for c in store.chats(simulated=True)}
    seed, rows, silent = assumptions["seed"], [], []
    for day in sorted({r["sim_day"] for r in old}):
        sessions = []
        for v in make_visitors(day, assumptions, orders, profiles, share, seed):
            sid = chat_of[(day, v.id)]
            replies = replies_of(sid) if v.group == ASSISTANT else []
            if v.group == ASSISTANT and v.intent == ORDER_STATUS and not replies and not stored.get(sid, {}).get("handed_off"):
                silent.append(sid)
            sessions.append((v, sid, replies))
        rows += outcome_rows(day, sessions, store, truth, assumptions, seed)
    if silent:
        raise SystemExit(f"no replies found for {len(silent)} assistant order-status chats that were not handed off "
                         f"({', '.join(silent[:3])}...): nothing was rescored")
    write_labels(store, rows)
    return rows


def replace_out(out, rows):
    """Write the rescored rows over `out`, after copying the old file aside. Each rescore keeps its own copy
    (`.before-rescore`, `.before-rescore-2`, ...); a copy is never overwritten. Returns the copy's path."""
    out = Path(out)
    kept = out.with_name(out.name + ".before-rescore")
    n = 1
    while kept.exists():
        n += 1
        kept = out.with_name(f"{out.name}.before-rescore-{n}")
    shutil.copy2(out, kept)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return kept


def trace_replies(url):
    """{chat id: the text of every reply the model gave in that chat} from the `traces` table (read only)."""
    import psycopg
    by_chat = {}
    with psycopg.connect(url) as conn:
        for sid, raw in conn.execute("SELECT session_id, reply FROM traces WHERE kind = 'chat' ORDER BY at"):
            try:
                blocks = json.loads(raw)
            except (TypeError, ValueError):
                blocks = [{"type": "text", "text": raw}]
            by_chat.setdefault(sid, []).extend(b["text"] for b in blocks
                                               if isinstance(b, dict) and b.get("type") == "text" and b.get("text"))
    return lambda sid: by_chat.get(sid, [])


# ---- the drill: the night the carrier's file does not come ----------------------------------------------------------------
# The service keeps the load of the 22nd and is pinned to the morning of the 23rd. The hidden file of the 23rd is what the
# carrier would have sent: it is only used to score the replies, and is not in the folder the SFTP server serves.

def drill_night(rows):
    """The 22nd's rows moved one night on: out for delivery -> delivered at the front door, in transit -> out for delivery,
    delivered stays. Every moved parcel carries the date of the 23rd."""
    night = []
    for r in rows:
        r = dict(r)
        if r["status"] == "out for delivery":
            r.update(status="delivered", place="front door", date="2026-10-23")
        elif r["status"] == "in transit":
            r.update(status="out for delivery", date="2026-10-23")
        night.append(r)
    return night


def write_drill_night(path=DRILL_FILE):
    """Write the hidden file of the 23rd from the newest file on the SFTP folder (the 22nd)."""
    _, rows = newest_carrier()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tracking", "status", "place", "date"], extrasaction="ignore",
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(drill_night(rows))
    return path


def load_drill_truth(orders_path=HERE / "data" / "orders.json", path=DRILL_FILE):
    """(orders, truth of the night of the 23rd): what is really the matter with each order after the missing night."""
    with open(orders_path) as f:
        orders = json.load(f)
    rows = carrier.parse(Path(path).read_bytes(), str(path))
    return orders, build_truth(orders, [{**r, "date": r["date"].isoformat()} for r in rows])


def drill_orders(orders, rows22):
    """(exposed, final): orders with a parcel that is not delivered in the 22nd's file (the news the service holds, a day old
    on the 23rd), and orders that were delivered already (final: the guard must leave them alone)."""
    news = {r["tracking"]: r["status"] for r in rows22}
    exposed = [o for o in orders if any(news.get(t, "delivered") != "delivered" for t in o["tracking"])]
    truth = build_truth(orders, rows22)
    final = [o for o in orders if o["tracking"] and truth[o["number"]]["status"] == "delivered"]
    return exposed, final


def drill_config(assumptions, day):
    days = assumptions["drill"]["days"]
    if str(day) not in days:
        raise SystemExit(f"no drill day {day}: the planned drill days are {', '.join(days)}")
    return days[str(day)]


def make_drill_visitors(day, assumptions, orders, rows22, share=SHARE, seed=None):
    """The assistant conversations of a drill day, all order status, `delivered` of them on delivered orders. Every visitor
    id hashes into the assistant group at `share`, so the service routes them as the assistant's."""
    seed = assumptions["seed"] if seed is None else seed
    config = drill_config(assumptions, day)
    exposed, final = drill_orders(orders, rows22)
    rng = random.Random(f"{seed}-drill-{day}")
    low, high = assumptions["followups"]
    picks = ([rng.choice(exposed) for _ in range(config["conversations"] - config["delivered"])]
             + [rng.choice(final) for _ in range(config["delivered"])])
    rng.shuffle(picks)
    visitors, k = [], 0
    for order in picks:
        while golive.group_of(vid := f"drill-{seed}-d{day:02d}-{k:04d}", share) != ASSISTANT:
            k += 1
        k += 1
        messages = [rng.choice(FIRST).format(order=order["number"], weekday=rng.choice(["Monday", "Friday"]))]
        messages += rng.sample(FOLLOW, rng.randint(low, high))
        visitors.append(Visitor(vid, day, ASSISTANT, ORDER_STATUS, order["customer"], order["number"], messages, False,
                                "drill"))
    return visitors


def drill_ceiling(assumptions):
    return assumptions["assistant_cap"] + assumptions["drill"]["extra_cap"]


def plan_drill(assumptions, day, share=SHARE, already=0, orders=None, rows22=None):
    """What a drill day would do, without doing it."""
    if orders is None:
        orders, _ = load_truth()
    rows22 = newest_carrier()[1] if rows22 is None else rows22
    visitors = make_drill_visitors(day, assumptions, orders, rows22, share)
    est, truth22 = assumptions["estimate"], build_truth(orders, rows22)
    calls = sum(calls_for(v, est) for v in visitors)
    price_in, price_out = llm.PRICES[llm.MODEL]
    cost = (calls * est["input_tokens_per_call"] * price_in + calls * est["output_tokens_per_call"] * price_out) / 1_000_000
    return {"day": day, "assistant": len(visitors), "used": already, "ceiling": drill_ceiling(assumptions),
            "cap": assumptions["assistant_cap"], "extra": assumptions["drill"]["extra_cap"], "calls": calls, "cost": cost,
            "exposed": sum(1 for v in visitors if truth22[v.order]["status"] != "delivered"),
            "final": sum(1 for v in visitors if truth22[v.order]["status"] == "delivered"), "model": llm.MODEL}


def describe_drill(p):
    lines = [f"SIMULATED drill day {p['day']} - the night with no carrier file",
             (f"assistant conversations: {p['assistant']} ({p['used']} used so far; {p['used'] + p['assistant']} of at most "
              f"{p['ceiling']}: the cap {p['cap']} plus {p['extra']} for the drill)"),
             f"on orders with an undelivered parcel: {p['exposed']}; on delivered orders (control): {p['final']}",
             "no control traffic: a drill day sends only the assistant's conversations",
             f"expected model calls: {p['calls']} ({p['model']})",
             f"cost estimate: ${p['cost']:.2f} (from llm.PRICES and the token estimates in sim_assumptions.json)"]
    if p["used"] + p["assistant"] > p["ceiling"]:
        lines.append(f"STOPPED: this day would pass {p['ceiling']} assistant conversations; it is not run")
    return "\n".join(lines)


def run_drill(day, assumptions, gateway, store, out, share, orders, night_truth, rows22, say=print):
    """Run one drill day against the service, scored against the hidden truth of the night. The ceiling is the cap plus the
    drill allowance; a day that would pass it is not run. Returns the rows (none when it stopped)."""
    drill_config(assumptions, day)
    done = read_out(out)
    if day in {r["sim_day"] for r in done}:
        raise SystemExit(f"sim day {day} is already in {out}: not run again")
    used = sum(1 for r in done if r["group"] == ASSISTANT)
    visitors = make_drill_visitors(day, assumptions, orders, rows22, share)
    ceiling = drill_ceiling(assumptions)
    if used + len(visitors) > ceiling:
        say(f"STOPPED: drill day {day} would pass the ceiling of {ceiling} assistant conversations "
            f"({used} used, {len(visitors)} more); it is not run")
        return []
    rows = run_day(day, visitors, gateway, store, night_truth, assumptions, assumptions["seed"])
    append_out(out, rows)
    lost = write_labels(store, rows)
    say(f"drill day {day}: {len(rows)} assistant conversations ({used + len(rows)} of {ceiling}), confidently wrong "
        f"{sum(r['confidently_wrong'] for r in rows)}" + (f"; {lost} chats are not in the service table" if lost else ""))
    return rows


class LocalGateway(HttpGateway):
    """The chat service in this process (FastAPI's test client) instead of over HTTP, for a replay."""

    def __init__(self, client, outbox):
        super().__init__("http://local", outbox)
        self.client = client

    def post(self, path, body):
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()


def replay_drill(day, assumptions, orders, night_truth, rows22, share=SHARE, outbox="data/outbox-replay.jsonl", say=print):
    """The drill day's chats again, through the chat service in this process, on the code as it is now and with the model
    live. Nothing real is touched: its own go-live table, a fake ServiceNow and drafts, a fake traces sink, its own sessions
    and outbox. Scored against the hidden truth of the night; returns the rows."""
    from fastapi.testclient import TestClient

    import app as chat_app
    import drafts
    import refunds
    import servicenow
    import traces
    import verify

    kept = (chat_app.golive_store, chat_app.SESSIONS, verify._default, traces._sink, refunds._drafts, refunds._servicenow)
    local = golive.FakeGoLiveStore()
    local.create_tables()
    local.set_settings(share=share, intents=["order_status"], on=True)
    Path(outbox).unlink(missing_ok=True)
    try:
        chat_app.golive_store = lambda: local
        chat_app.SESSIONS = {}
        verify._default = verify.Verifier(outbox=str(outbox))
        traces._sink = traces.FakeTraces()
        refunds._drafts, refunds._servicenow = drafts.FakeDrafts(), servicenow.FakeServiceNow()
        visitors = make_drill_visitors(day, assumptions, orders, rows22, share)
        rows = run_day(day, visitors, LocalGateway(TestClient(chat_app.app), outbox), local, night_truth, assumptions,
                       assumptions["seed"])
    finally:
        chat_app.golive_store, chat_app.SESSIONS, verify._default, traces._sink, refunds._drafts, refunds._servicenow = kept
        Path(outbox).unlink(missing_ok=True)
    say(f"replay of drill day {day}: {len(rows)} assistant conversations, confidently wrong "
        f"{sum(r['confidently_wrong'] for r in rows)}")
    return rows


def run(days, assumptions, gateway, store, out=OUT, share=SHARE, orders=None, truth=None, profiles=None, say=print):
    """Run sim days one at a time. A day already in `out` is refused; a day that would pass the cap stops the run."""
    if assumptions["control_repeat_rate"] is None:
        raise SystemExit("control_repeat_rate is not computed yet: run `python golive_sim.py --refresh-repeat`")
    if orders is None or truth is None:
        orders, truth = load_truth()
    profiles = load_profiles() if profiles is None else profiles
    seed = assumptions["seed"]
    done = read_out(out)
    have = {r["sim_day"] for r in done}
    used = sum(1 for r in done if r["group"] == ASSISTANT)
    for day in days:
        if day in have:
            raise SystemExit(f"sim day {day} is already in {out}: not run again")
        visitors = make_visitors(day, assumptions, orders, profiles, share, seed)
        mine = sum(1 for v in visitors if v.group == ASSISTANT)
        if used + mine > assumptions["assistant_cap"]:
            say(f"STOPPED: sim day {day} would pass the cap of {assumptions['assistant_cap']} assistant conversations "
                f"({used} used, {mine} more); it and the later days are not run")
            return
        rows = run_day(day, visitors, gateway, store, truth, assumptions, seed)
        append_out(out, rows)
        lost = write_labels(store, rows)
        if lost:
            say(f"sim day {day}: {lost} chats are not in the service table (the service did not record them)")
        used += mine
        say(f"sim day {day}: {len(rows)} visitors, {mine} assistant conversations ({used} of "
            f"{assumptions['assistant_cap']}), confidently wrong {sum(r['confidently_wrong'] for r in rows)}")


def parse_days(text, total):
    first, _, last = text.partition("-")
    days = range(int(first), int(last or first) + 1)
    if not days or days[0] < 1 or days[-1] > total:
        raise SystemExit(f"--days must be inside 1-{total}")
    return list(days)


def refresh_repeat(path=ASSUMPTIONS):
    """Read the old chats (reader account, GET only) and write the control repeat rate into the assumptions."""
    import shadow
    old = shadow.query(shadow.http_get, "ORDERBYopened_at")
    assumptions = load_assumptions(path)
    rate, n = repeat_rate(old, assumptions["repeat_window_days"])
    assumptions["control_repeat_rate"], assumptions["control_repeat_rate_n"] = rate, n
    Path(path).write_text(json.dumps(assumptions, indent=2) + "\n")
    return rate, n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the plan; write nothing, call nothing")
    ap.add_argument("--days", default=None, help="sim days to run, e.g. 1-7 or 3 (default: all)")
    ap.add_argument("--share", type=float, default=SHARE)
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--outbox", default="data/outbox.jsonl")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--refresh-repeat", action="store_true")
    ap.add_argument("--rescore", action="store_true", help="score the stored chats again from the traces; no model call")
    ap.add_argument("--drill-day", type=int, default=None, help="run a drill day (15, then 16): the night with no carrier file")
    ap.add_argument("--write-drill-night", action="store_true", help="write the hidden carrier file of the 23rd")
    ap.add_argument("--replay-drill", type=int, default=None, help="replay a drill day's chats in this process (live model)")
    args = ap.parse_args(argv)
    if args.refresh_repeat:
        rate, n = refresh_repeat()
        print(f"control repeat rate within 7 days: {rate:.3f} of {n} old chats (written to sim_assumptions.json)")
        return 0
    if args.write_drill_night:
        print(f"wrote {write_drill_night()}")
        return 0
    assumptions = load_assumptions()
    if args.replay_drill is not None:
        orders, _ = load_truth()
        rows = replay_drill(args.replay_drill, assumptions, orders, load_drill_truth()[1], newest_carrier()[1], args.share)
        for r in rows:
            print(f"{'WRONG' if r['confidently_wrong'] else 'ok   '} {r['order']} night truth {r['true_status']} "
                  f"outcome {r['outcome']} | {(r['last_reply'] or '')[:150]!r}")
        return 0
    if args.drill_day is not None:
        orders, _ = load_truth()
        rows22 = newest_carrier()[1]
        already = sum(1 for r in read_out(args.out) if r["group"] == ASSISTANT)
        if args.dry_run:
            print(describe_drill(plan_drill(assumptions, args.drill_day, args.share, already, orders, rows22)))
            return 0
        run_drill(args.drill_day, assumptions, HttpGateway(args.url, args.outbox), golive.GoLiveStore(), args.out, args.share,
                  orders, load_drill_truth()[1], rows22)
        return 0
    if args.rescore:
        import config
        orders, truth = load_truth()
        rows = rescore(assumptions, golive.GoLiveStore(), truth, trace_replies(config.store_url()), args.out, orders,
                       load_profiles(), args.share)
        kept = replace_out(args.out, rows)
        print(f"rescored {len(rows)} rows against {newest_carrier()[0]}: confidently wrong "
              f"{sum(r['confidently_wrong'] for r in rows)}; the old file is {kept}")
        return 0
    days = parse_days(args.days, assumptions["days"]) if args.days else list(range(1, assumptions["days"] + 1))
    already = sum(1 for r in read_out(args.out) if r["group"] == ASSISTANT)
    if args.dry_run:
        print(describe(plan(assumptions, days, args.share, already)))
        return 0
    print(describe(plan(assumptions, days, args.share, already)))
    run(days, assumptions, HttpGateway(args.url, args.outbox), golive.GoLiveStore(), args.out, args.share)
    return 0


if __name__ == "__main__":
    sys.exit(main())
