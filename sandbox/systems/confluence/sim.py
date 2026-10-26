"""A small stand-in for DemoStore's Confluence: the policy space POL, one page per policy and market.

    labs/.venv/bin/uvicorn sim:app --app-dir systems/confluence --port 8040      (from the sandbox folder)

GET /rest/api/content?spaceKey=POL&expand=body,version,metadata -> {"results": [{"id", "title", "version": {"number", "when"},
    "metadata": {"market", "valid_from", "valid_to"}, "body", "_links": {"webui"}}]}
    The body is plain text, each section under a line that starts with "## " (the real API sends XHTML).
GET /wiki/spaces/POL                    -> the space's page list, as a person sees it (HTML)
GET /wiki/spaces/POL/pages/{id}         -> one page (HTML): its version, when it was edited, its dates, its sections
POST /admin/reset                       -> every page back to the start of the policy lessons (FDE 1-8-7)
POST /admin/change-de-window            -> the policy team's edit of yesterday: Germany's return window goes from 14 to
                                           30 days, valid from yesterday (version 2 of the page)

Each page holds the version a customer sees today or from a later date: a policy that changes later is a second page
with its own "valid from" date, and the page it replaces ends the day before (the UK delivery rule that starts in ten
days). Dates are worked out from today when the server starts or a page changes. The rules match the sandbox's return
code (returns.py, FDE 1-7-3): 14 days in the UK, Germany, France and Italy; 30 days in the US, 15 if opened; opened
earbuds and opened software never; company customers always through a person. Pages live in memory only; no auth.
"""
import html
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(title="Confluence (DemoStore sandbox)")

START = "2026-01-01"
EARLIER = "2026-09-14"   # when the pages were last edited before the lessons start

RETURNS_EU = """## Return window
You can return an item within {days} days of delivery, opened or not. The {days} days start on the day the parcel is delivered.

## Condition
Send the item back with everything that came in the box. Opened earbuds and opened software cannot be returned, for hygiene and licence reasons.

## Refunds
We refund the price and the original delivery cost within 14 days of receiving the item, to the payment method you used.

## Company customers
Customers of DemoStore Business return items under the terms of their contract. A person from our team handles every company return."""

RETURNS_US = """## Return window
You can return an item within 30 days of delivery. An opened item can be returned within 15 days of delivery.

## Condition
Send the item back with everything that came in the box. Opened earbuds and opened software cannot be returned.

## Refunds
We refund the price within 10 business days of receiving the item, to the payment method you used. Delivery costs are not refunded.

## Company customers
Customers of DemoStore Business return items under the terms of their contract. A person from our team handles every company return."""

WARRANTY_EU = """## What the warranty covers
Every item has a two-year warranty from the day of delivery. It covers faults in materials and manufacturing, such as a screen that stops working or a keyboard key that fails.

## What it does not cover
The warranty does not cover accidental damage: a drop, a spill or a cracked screen after a fall. It does not cover normal wear, such as a worn battery after two years.

## How to claim
Open a warranty claim in your account with the order number and a photo of the fault. We repair or replace the item, and we pay for the shipping."""

WARRANTY_US = """## What the warranty covers
Every item has a one-year limited warranty from the day of delivery. It covers faults in materials and manufacturing.

## What it does not cover
The warranty does not cover accidental damage: a drop, a spill or a cracked screen after a fall. It does not cover normal wear.

## How to claim
Open a warranty claim in your account with the order number and a photo of the fault. We repair or replace the item."""

DELIVERY_UK = """## Delivery costs
Standard delivery is free on orders over {free} pounds. Below that, it costs 4.99 pounds.

## Delivery times
Standard delivery takes two to four working days. Next-day delivery costs 7.99 pounds if you order before 2 pm."""

DELIVERY_EU = """## Delivery costs
Standard delivery is free on orders over 50 euros. Below that, it costs 4.99 euros.

## Delivery times
Standard delivery takes two to five working days."""

DELIVERY_US = """## Delivery costs
Standard delivery is free on orders over 50 dollars. Below that, it costs 5.99 dollars.

## Delivery times
Standard delivery takes three to five business days."""

NAMES = {"UK": "UK", "DE": "Germany", "FR": "France", "IT": "Italy", "US": "US"}


def start_pages():
    """The policy space as it was before the lessons: every page valid from the start of the year."""
    today = date.today()
    later = today + timedelta(days=10)
    pages = []
    page_id = 1001
    for market in ["UK", "DE", "FR", "IT", "US"]:
        returns = RETURNS_US if market == "US" else RETURNS_EU.format(days=14)
        warranty = WARRANTY_US if market == "US" else WARRANTY_EU
        if market == "UK":
            delivery = DELIVERY_UK.format(free=50)
        elif market == "US":
            delivery = DELIVERY_US
        else:
            delivery = DELIVERY_EU
        for kind, body in [("Returns", returns), ("Warranty", warranty), ("Delivery", delivery)]:
            pages.append({"id": str(page_id), "title": f"{kind} - {NAMES[market]}", "market": market, "body": body,
                          "version": 3 if kind == "Returns" else 2, "when": EARLIER,
                          "valid_from": START, "valid_to": None})
            page_id += 1
    # the UK delivery rule that starts in ten days is already published, next to the one it replaces
    for page in pages:
        if page["title"] == "Delivery - UK":
            page["valid_to"] = (later - timedelta(days=1)).isoformat()
    pages.append({"id": str(page_id), "title": "Delivery - UK (new rule)", "market": "UK",
                  "body": DELIVERY_UK.format(free=30), "version": 1, "when": EARLIER,
                  "valid_from": later.isoformat(), "valid_to": None})
    return pages


PAGES = start_pages()


def find(page_id):
    for page in PAGES:
        if page["id"] == page_id:
            return page
    raise HTTPException(404, f"no page {page_id}")


def as_api(page):
    return {"id": page["id"], "type": "page", "title": page["title"],
            "version": {"number": page["version"], "when": page["when"]},
            "metadata": {"market": page["market"], "valid_from": page["valid_from"], "valid_to": page["valid_to"]},
            "body": page["body"], "_links": {"webui": f"/wiki/spaces/POL/pages/{page['id']}"}}


@app.get("/rest/api/content")
def content(spaceKey: str = "POL", expand: str = ""):
    if spaceKey != "POL":
        raise HTTPException(404, f"no space {spaceKey}")
    return {"results": [as_api(p) for p in PAGES], "size": len(PAGES)}


@app.post("/admin/reset")
def reset():
    PAGES[:] = start_pages()
    return {"pages": len(PAGES)}


@app.post("/admin/change-de-window")
def change_de_window():
    page = next(p for p in PAGES if p["title"] == "Returns - Germany")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    page["body"] = RETURNS_EU.format(days=30)
    page["version"] += 1
    page["when"] = yesterday
    page["valid_from"] = yesterday
    return as_api(page)


STYLE = """<style>body{font-family:-apple-system,Segoe UI,sans-serif;margin:0;color:#172b4d;background:#fff}
header{background:#0c66e4;color:#fff;padding:10px 24px;font-weight:600}main{padding:20px 28px;max-width:760px}
h1{font-size:24px;margin:4px 0 6px}h2{font-size:17px;margin:20px 0 4px}.meta{color:#626f86;font-size:13px}
.dates{display:inline-block;background:#e9f2ff;border-radius:3px;padding:3px 8px;margin:8px 0;font-size:13px}
li{margin:6px 0}a{color:#0c66e4;text-decoration:none}p{line-height:1.45;margin:4px 0}</style>"""


@app.get("/wiki/spaces/POL", response_class=HTMLResponse)
def space():
    rows = "".join(f'<li><a href="/wiki/spaces/POL/pages/{p["id"]}">{html.escape(p["title"])}</a> '
                   f'<span class="meta">valid from {p["valid_from"]}</span></li>' for p in PAGES)
    return f"<!doctype html><title>Policies</title>{STYLE}<header>Confluence · DemoStore</header>" \
           f"<main><h1>Policies</h1><ul>{rows}</ul></main>"


@app.get("/wiki/spaces/POL/pages/{page_id}", response_class=HTMLResponse)
def page_view(page_id: str):
    page = find(page_id)
    body = ""
    for part in page["body"].split("## ")[1:]:
        title, text = part.split("\n", 1)
        body += f"<h2>{html.escape(title)}</h2><p>{html.escape(text.strip())}</p>"
    until = f" until {page['valid_to']}" if page["valid_to"] else ""
    return f"<!doctype html><title>{html.escape(page['title'])}</title>{STYLE}<header>Confluence · DemoStore</header>" \
           f"<main><div class='meta'>Policies</div><h1>{html.escape(page['title'])}</h1>" \
           f"<div class='meta'>Version {page['version']}, edited {page['when']}</div>" \
           f"<div class='dates'>Valid from {page['valid_from']}{until}</div>{body}</main>"
