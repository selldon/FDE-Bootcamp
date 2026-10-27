"""A small stand-in for DemoStore's ServiceNow: the Table API for old chat interactions.

    labs/.venv/bin/uvicorn sim:app --app-dir systems/servicenow --port 8020      (from the sandbox folder)
    labs/.venv/bin/python systems/servicenow/sim.py export data/business_view.csv  (the Business team's list export)

GET /api/now/table/interaction?sysparm_limit=100&sysparm_offset=0&sysparm_query=ORDERBYopened_at answers like
ServiceNow: {"result": [...]} (at most 100 records a page), the number of all records in the X-Total-Count header, basic auth (test account fde_reader / reader, read
only). More than five requests in one second get 429 Too Many Requests with Retry-After: 1. The 2,040 chats are made
up once at start, the same every time (seeded): customers, products and questions like DemoStore's real chats.

What the cleaning lesson (FDE 1-6-4) needs is in the data too, from a second seeded generator so the chats of the pull
stay as they were: a customer's market is the market of their account in Ledgerline, a few chats have no market, a few
customers typed a phone number (fictional numbers), and the DemoStore Business team's view comes as a CSV export in
the exporting user's local time (Europe/Berlin): the chats the support team passed to them, plus their own.

Approval tasks for refund drafts (FDE 1-7-7): POST /api/now/table/sc_task opens one, GET with
sysparm_query=approval!=requested lists the decided ones (integration account fde_tasks / tasks), and the support team
approves or rejects them on the page /tasks. Tasks live in memory only.

Live chat (FDE 1-11-2): POST /api/now/table/interaction (same account) puts a chat the website hands to a person into
the support team's queue, one waiting chat per conversation; the page /live shows the queue. In memory only.

Incoming live chats (FDE 1-9-12, shadow mode): with SNOW_INCOMING_EVERY=<seconds> (0, the default, turns it off) a
customer opens a new chat with the support team every so many seconds, from the 60 in incoming.json (DemoStore's real
orders and their owners). After SNOW_INCOMING_OPEN seconds (default 240) an agent has answered and the chat is closed,
with the reply in the transcript. They come with the old chats from the Table API; a poller asks for the new ones with
sysparm_query=opened_at>YYYY-MM-DD HH:MM:SS^ORDERBYopened_at (UTC), and for one chat with number=IMS...
"""
import csv
import hashlib
import json
import os
import random
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

COUNT = 2040
LIMIT_MAX = 100
PER_SECOND = 5

app = FastAPI(title="ServiceNow (DemoStore sandbox)")
basic = HTTPBasic()

MARKETS = ["UK", "US", "DE", "FR", "IT"]
NAMES = ["Maya Ross", "Tom Baker", "Lea Schmidt", "Paul Martin", "Giulia Conti", "Sam Lee", "Ines Dubois", "Ben Taylor",
         "Lena Fischer", "Marco Bianchi", "Luca Ferri", "Anna Weber", "Chloe Martin", "Oliver Smith", "Sofia Ricci"]
ITEMS = ["Aero 14 laptop", "Aero 14 Pro laptop", "Nova 24 monitor", "Nova 27 monitor", "Volt 8 graphics card",
         "Wi-Fi router R6", "SSD 1 TB", "Keyboard K2", "Mouse M3", "Power supply 850 W", "Headset H5", "Webcam C2"]
QUESTIONS = [  # (intent, share, message templates)
    ("order_status", 38, ["Hi, where is my order {order}? It was due on {day}.", "When will order {order} arrive?",
                          "Order {order} still says processing. When will it ship?", "Tracking for {order} has not moved for three days."]),
    ("return_request", 20, ["I want to return the {item} from order {order}. It is too loud.",
                            "The {item} from {order} arrived broken. How do I send it back?",
                            "Can I still return the {item}? I bought it {days} days ago."]),
    ("policy_question", 15, ["How many days do I have to return something I bought online?",
                             "Is the warranty on a {item} one year or two?", "Do you deliver to {market} on Saturdays?"]),
    ("product_question", 13, ["Is the {item} in stock?", "Does the {item} work with a Mac?", "What is the difference between the Aero 14 and the Aero 14 Pro?"]),
    ("contract_price", 5, ["We have a company account. What is our price for {qty} {item}s?",
                           "I buy for my small office. Do you give a discount if I order {qty} monitors?"]),
    ("other", 9, ["Third time I am writing. I want a real person, now!", "Do you buy back old laptops?",
                  "Please change the email on my account to {email}."]),
]
# the market of the customer's account in Ledgerline (LL_CUST.MKT_CD), for the customers who have one
HOME = {"Maya Ross": "UK", "Tom Baker": "UK", "Lea Schmidt": "US", "Paul Martin": "DE", "Sam Lee": "UK", "Ines Dubois": "DE",
        "Ben Taylor": "FR", "Lena Fischer": "US", "Marco Bianchi": "US", "Luca Ferri": "US"}
PHONES = {"UK": "020 7946 0{n:03d}", "US": "+1 202 555 0{n:03d}", "DE": "030 23125 {n:03d}", "FR": "01 99 00 {n:03d}",
          "IT": "+39 02 0000 0{n:03d}"}  # number ranges kept for fiction, nobody's real number
REPLIES = {
    "order_status": "Thanks, I checked: the parcel is with the carrier and should arrive within two days.",
    "return_request": "I have opened a return for you. You will get a label by email.",
    "policy_question": "Our policy page has the details, and I have sent you the link.",
    "product_question": "Let me check that with the team and come back to you today.",
    "contract_price": "I have passed this to our business sales team, they will send you an offer.",
    "other": "I understand. A colleague will take over this chat.",
}


INTENT_OF = {}


def make_chats():
    rnd = random.Random(2026)
    more = random.Random(1604)        # the additions for the cleaning lesson, so rnd gives the same chats as before
    shares = [q[1] for q in QUESTIONS]
    start = datetime(2026, 4, 1, 8, 0, 0)
    chats = []
    for i in range(COUNT):
        intent, _, templates = rnd.choices(QUESTIONS, weights=shares)[0]
        name = rnd.choice(NAMES)
        email = name.lower().replace(" ", ".") + "@example.com"
        market = rnd.choice(MARKETS)
        market = HOME.get(name, market)   # a known customer buys from the market of their account
        message = rnd.choice(templates).format(
            order=f"DS-{18000 + rnd.randrange(2400)}", item=rnd.choice(ITEMS), day=rnd.choice(["Monday", "Tuesday", "Friday"]),
            days=rnd.randrange(5, 40), market=market, qty=rnd.choice([5, 10, 20]), email=email)
        if rnd.random() < 0.02:  # customers sometimes paste a card number into the chat
            message += " My card is 4111 1111 1111 1111 if you need it."
        if i > 0 and more.random() < 0.03:  # ... or a phone number
            message += " You can call me on " + PHONES[market].format(n=more.randrange(1000)) + "."
        if i > 0 and name in HOME and more.random() < 0.05:  # the market field left empty: the account still has it
            market_field = ""
        else:
            market_field = market
        opened = start + timedelta(minutes=127 * i + rnd.randrange(60))
        chats.append({
            "sys_id": hashlib.md5(f"chat-{i}".encode()).hexdigest(),
            "number": f"IMS{1001 + i:07d}",
            "opened_at": opened.strftime("%Y-%m-%d %H:%M:%S"),
            "channel": "chat",
            "state": "closed_complete",
            "u_market": market_field,
            "opened_for": email,
            "short_description": message[:80],
            "transcript": f"{name}: {message}\nAgent: {REPLIES[intent]}",
        })
        INTENT_OF[chats[-1]["number"]] = intent   # for the Business export below; never sent
    return chats


CHATS = make_chats()
calls = []


def reader(cred: HTTPBasicCredentials = Depends(basic)):
    if not (secrets.compare_digest(cred.username, "fde_reader") and secrets.compare_digest(cred.password, "reader")):
        raise HTTPException(401, "User Not Authenticated", headers={"WWW-Authenticate": "Basic"})


@app.get("/api/now/table/interaction", dependencies=[Depends(reader)])
def interactions(request: Request, response: Response, sysparm_limit: int = 100, sysparm_offset: int = 0,
                 sysparm_query: str = ""):
    now = time.monotonic()
    calls[:] = [t for t in calls if now - t < 1.0] + [now]
    if len(calls) > PER_SECOND:
        raise HTTPException(429, "Too Many Requests: rate limit exceeded", headers={"Retry-After": "1"})
    limit = max(1, min(sysparm_limit, LIMIT_MAX))
    rows = CHATS + incoming()
    for part in sysparm_query.split("^"):              # a small part of ServiceNow's encoded queries
        if part.startswith("ORDERBY"):
            rows = sorted(rows, key=lambda c: c.get(part[7:], ""))
        elif ">" in part:
            field, value = part.split(">", 1)
            rows = [c for c in rows if c.get(field, "") > value]
        elif "=" in part:
            field, value = part.split("=", 1)
            rows = [c for c in rows if c.get(field, "") == value]
    response.headers["X-Total-Count"] = str(len(rows))
    return {"result": rows[sysparm_offset:sysparm_offset + limit]}


EVERY = int(os.environ.get("SNOW_INCOMING_EVERY", "0"))
OPEN_FOR = int(os.environ.get("SNOW_INCOMING_OPEN", "240"))
POOL = json.loads(Path(__file__).with_name("incoming.json").read_text())
STARTED = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
EPOCH = datetime(2026, 10, 1)  # where the live chats' numbers count from (UTC); see incoming()


def incoming(now=None, started=None):
    """The live chats opened since the stand-in started, one every EVERY seconds; closed with the agent's reply after
    OPEN_FOR seconds. Made up from the clock on every request, so they are the same however often a poller asks.

    Chat k opens at EPOCH + EVERY*k and is numbered from k, not from the start of this process: a stand-in that is
    recreated (a deploy does it) goes on with the numbers of the clock and never hands out one twice, as a real
    ServiceNow never does. Keep EVERY the same between starts, or the slots (and the numbers) move."""
    if not EVERY:
        return []
    now = now or datetime.now(UTC).replace(tzinfo=None)
    started = started or STARTED
    first = int((started - EPOCH).total_seconds() // EVERY) + 1   # the first slot after the start
    last = int((now - EPOCH).total_seconds() // EVERY)            # the last slot that has come
    rows = []
    for k in range(first, last + 1):
        chat = POOL[k % len(POOL)]
        opened = EPOCH + timedelta(seconds=EVERY * k)
        closed = now >= opened + timedelta(seconds=OPEN_FOR)
        rows.append({
            "sys_id": hashlib.md5(f"incoming-{k}".encode()).hexdigest(),
            "number": f"IMS{5001 + k:07d}",
            "opened_at": opened.strftime("%Y-%m-%d %H:%M:%S"),
            "channel": "chat",
            "state": "closed_complete" if closed else "work_in_progress",
            "u_market": chat["market"],
            "opened_for": chat["email"],
            "short_description": chat["message"][:80],
            "transcript": f"{chat['name']}: {chat['message']}" + (f"\nAgent: {chat['reply']}" if closed else ""),
        })
    return rows


BUSINESS = [("Ines Dubois", "DE"), ("Jonas Weber", "DE"), ("Felix Braun", "US")]
BUSINESS_QUESTIONS = ["Please send a copy of the invoice for order {order}, our accounts team needs it.",
                      "We need {qty} {item}s for a new office. Can you hold them for a week?",
                      "Our contract price for the {item} is not applied in the basket. Can you check?",
                      "Who approves orders above the limit on our company account?"]


def business_view():
    """The DemoStore Business team's list, exported to CSV in the exporting user's time zone (Europe/Berlin): the chats
    the support team passed to them (the contract price questions), and 60 that came to the team directly."""
    rnd = random.Random(7)
    berlin, utc = ZoneInfo("Europe/Berlin"), ZoneInfo("UTC")
    rows = []

    def local(opened):
        when = datetime.strptime(opened, "%Y-%m-%d %H:%M:%S").replace(tzinfo=utc)
        return when.astimezone(berlin).strftime("%Y-%m-%d %H:%M:%S")

    for chat in CHATS:
        if INTENT_OF[chat["number"]] == "contract_price":
            rows.append([chat["number"], local(chat["opened_at"]), chat["u_market"], chat["opened_for"], chat["transcript"]])
    start = datetime(2026, 4, 2, 9, 0, 0)
    for k in range(60):
        name, market = rnd.choice(BUSINESS)
        message = rnd.choice(BUSINESS_QUESTIONS).format(order=f"DS-{18000 + rnd.randrange(2400)}", qty=rnd.choice([5, 10, 20]),
                                                        item=rnd.choice(ITEMS))
        opened = (start + timedelta(hours=59 * k + rnd.randrange(8))).strftime("%Y-%m-%d %H:%M:%S")
        number = f"IMS{1001 + COUNT + k:07d}"
        rows.append([number, local(opened), market, name.lower().replace(" ", ".") + "@example.com",
                     f"{name}: {message}\nAgent: I have passed this to our business sales team, they will reply today."])
    rows.sort(key=lambda r: r[1])
    return rows


# Approval tasks (FDE 1-7-7): the middleware opens one for each refund draft, a person approves or rejects it on the
# support team's page, and our poller reads the decided ones. Kept in memory: a restart starts with no tasks.
TASKS = []


def tasks_account(cred: HTTPBasicCredentials = Depends(basic)):
    if not (secrets.compare_digest(cred.username, "fde_tasks") and secrets.compare_digest(cred.password, "tasks")):
        raise HTTPException(401, "User Not Authenticated", headers={"WWW-Authenticate": "Basic"})


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.post("/api/now/table/sc_task", status_code=201, dependencies=[Depends(tasks_account)])
def create_task(body: dict):
    number = f"TASK{10001 + len(TASKS):07d}"
    task = {"sys_id": hashlib.md5(number.encode()).hexdigest(), "number": number,
            "short_description": str(body.get("short_description", ""))[:160], "u_draft": body.get("u_draft"),
            "approval": "requested", "sys_created_on": stamp(), "sys_updated_on": stamp()}
    TASKS.append(task)
    return {"result": task}


@app.get("/api/now/table/sc_task", dependencies=[Depends(tasks_account)])
def list_tasks(sysparm_query: str = ""):
    rows = TASKS
    if sysparm_query.startswith("approval!="):           # the queries the sandbox knows: approval=X, approval!=X
        rows = [t for t in TASKS if t["approval"] != sysparm_query[10:]]
    elif sysparm_query.startswith("approval="):
        rows = [t for t in TASKS if t["approval"] == sysparm_query[9:]]
    elif sysparm_query.startswith("u_draft="):            # the product looks a draft's task up by its key
        rows = [t for t in TASKS if t["u_draft"] == sysparm_query[8:]]
    return {"result": rows}


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Approvals - ServiceNow</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
body { font: 15px/1.4 -apple-system, "Segoe UI", sans-serif; margin: 0; background: #f4f5f7; color: #1d2733; }
header { background: #293e40; color: #fff; padding: 10px 16px; font-weight: 600; }
main { padding: 12px 16px; } .task { background: #fff; border-radius: 6px; padding: 10px 12px; margin-bottom: 10px;
box-shadow: 0 1px 2px rgba(0,0,0,.12); } .top { display: flex; justify-content: space-between; font-weight: 600; }
.state { font-weight: 500; color: #8a5a00; } .approved { color: #1c7c3c; } .rejected { color: #b42318; }
.desc { margin: 6px 0 8px; } button { font: inherit; padding: 4px 12px; margin-right: 6px; border-radius: 4px;
border: 1px solid #7a8a99; background: #fff; cursor: pointer; } button.ok { background: #1c7c3c; border-color: #1c7c3c;
color: #fff; } .none { color: #66717d; }
</style></head><body><header>ServiceNow - Approvals for the support team</header><main id="tasks">ROWS</main><script>
async function refresh() { const r = await fetch('/tasks/rows'); const html = await r.text();
  const box = document.getElementById('tasks'); if (box.innerHTML !== html) box.innerHTML = html; }
async function decide(number, what) { await fetch('/tasks/' + number + '/' + what, {method: 'POST'}); refresh(); }
setInterval(refresh, 1000);
</script></body></html>"""


def task_rows():
    if not TASKS:
        return '<p class="none">No approval tasks.</p>'
    out = []
    for t in reversed(TASKS):
        buttons = "" if t["approval"] != "requested" else (
            f'<button class="ok" onclick="decide(\'{t["number"]}\', \'approve\')">Approve</button>'
            f'<button onclick="decide(\'{t["number"]}\', \'reject\')">Reject</button>')
        out.append(f'<div class="task"><div class="top"><span>{t["number"]}</span><span class="state {t["approval"]}">'
                   f'{t["approval"]}</span></div><div class="desc">{t["short_description"]}</div>{buttons}</div>')
    return "".join(out)


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page():
    """The support team's view (logged in as a team member): open approvals first, newest on top."""
    return PAGE.replace("ROWS", task_rows())


@app.get("/tasks/rows", response_class=HTMLResponse)
def tasks_rows():
    return task_rows()


@app.post("/tasks/{number}/{decision}")
def decide(number: str, decision: str):
    for t in TASKS:
        if t["number"] == number and t["approval"] == "requested" and decision in ("approve", "reject"):
            t["approval"] = {"approve": "approved", "reject": "rejected"}[decision]
            t["sys_updated_on"] = stamp()
            return {"result": t}
    raise HTTPException(404, "no such open task")


# Live chat (FDE 1-11-2): a chat the website hands to a person waits in the support team's queue, the way every chat
# reached ServiceNow before the assistant. POST /api/now/table/interaction with a conversation id adds the message to
# that conversation's waiting chat (a new chat for a new id); the team sees the queue on the page /live. Kept in memory.
LIVE = {}


@app.post("/api/now/table/interaction", status_code=201, dependencies=[Depends(tasks_account)])
def open_chat(body: dict):
    conversation = str(body.get("u_conversation", ""))
    if conversation not in LIVE:
        number = f"IMS{1001 + len(LIVE):07d}"
        LIVE[conversation] = {"number": number, "state": "waiting for an agent", "opened_at": stamp(),
                              "u_conversation": conversation, "messages": []}
    chat = LIVE[conversation]
    chat["messages"].append(str(body.get("short_description", ""))[:160])
    return {"result": chat}


LIVE_PAGE = (PAGE.replace("Approvals - ServiceNow", "Live chat - ServiceNow")
             .replace("Approvals for the support team", "Live chats waiting for an agent")
             .replace("'/tasks/rows'", "'/live/rows'"))


def live_rows():
    if not LIVE:
        return '<p class="none">No chats waiting.</p>'
    out = []
    for chat in reversed(list(LIVE.values())):
        lines = "".join(f"<div>{m}</div>" for m in chat["messages"])
        out.append(f'<div class="task"><div class="top"><span>{chat["number"]}</span><span class="state">'
                   f'{chat["state"]}</span></div><div class="desc">{lines}</div></div>')
    return "".join(out)


@app.get("/live", response_class=HTMLResponse)
def live_page():
    """The support team's live chat queue, newest on top."""
    return LIVE_PAGE.replace("ROWS", live_rows())


@app.get("/live/rows", response_class=HTMLResponse)
def live_rows_html():
    return live_rows()


if __name__ == "__main__" and sys.argv[1:2] == ["export"]:
    with open(sys.argv[2], "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["number", "opened_at", "u_market", "opened_for", "transcript"])
        writer.writerows(business_view())
    print(f"{len(business_view())} chats -> {sys.argv[2]}")
