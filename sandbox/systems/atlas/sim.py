"""A small stand-in for Atlas, DemoStore's store platform: the catalog, public prices, company users and contract prices.

    labs/.venv/bin/uvicorn sim:app --app-dir systems/atlas --port 8030      (from the sandbox folder)

GET /products?name=Aero 14 laptop          -> {"sku", "name"}  the catalog entry whose name fits best (404 if none)
GET /products/{sku}/price?market=DE        -> {"sku", "price", "currency", "kind": "public"}
GET /users/{email}                         -> {"email", "company_id", "company", "roles"}  a DemoStore Business user,
                                              404 for everyone else (consumers have no company)
GET /companies/{company_id}/prices/{sku}   -> {"sku", "price", "currency", "kind": "contract", "company_id"}

The contract price is worked out from the company's price list on every call and takes about a second, the reason a
developer is tempted to cache it. SKUs and public prices are the same as in Ledgerline (systems/ledgerline/make_sql.py:
one price per item, in the market's currency). Two DemoStore Business companies in Germany agreed different prices for
the same products; their users have the roles buyer, approver and admin (a role is a named set of rights: a buyer places
orders, an approver approves them, an admin manages the company's users). No auth: a local sandbox.
"""
import time

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Atlas (DemoStore sandbox)")

CURRENCY = {"UK": "GBP", "US": "USD", "DE": "EUR", "FR": "EUR", "IT": "EUR"}
PRICE = {  # as in Ledgerline: one price per item, in the market's currency
    "laptop": 1299.00, "pro laptop": 1749.00, "monitor": 329.00, "graphics card": 699.00, "router": 129.00,
    "ssd": 89.00, "keyboard": 79.00, "mouse": 39.00, "power supply": 119.00, "headset": 99.00, "tablet": 449.00,
    "webcam": 69.00, "dock": 189.00, "printer": 249.00, "speaker": 129.00, "drive": 99.00,
}
ITEMS = ["Aero 14 laptop", "Aero 14 Pro laptop", "Nova 24 monitor", "Nova 27 monitor", "Nova 32 monitor",
         "Volt 8 graphics card", "Wi-Fi router R6", "SSD 1 TB", "SSD 2 TB", "Keyboard K2", "Mouse M3",
         "Power supply 850 W", "Gaming headset H3", "Headset H5", "Webcam W1", "Webcam C2", "Docking station D2",
         "Laser printer P5", "Inkjet printer P2", "Desk speakers S2", "Smart speaker S1", "Vento mini PC"]

COMPANIES = {"C-2001": "Kessler Systems GmbH", "C-2002": "Nordwerk IT GmbH"}
USERS = {  # email -> company, roles (the emails are the ones stored with their orders in Ledgerline)
    "ines.dubois@example.com": ("C-2001", ["buyer"]),
    "sara.conti@example.com": ("C-2001", ["approver"]),
    "jonas.weber@example.com": ("C-2002", ["buyer", "admin"]),
    "theo.roux@example.com": ("C-2002", ["admin"]),
}
CONTRACT = {  # company -> share of the public price agreed in its contract, and a few fixed prices
    "C-2001": (0.88, {"Aero 14 laptop": 1099.00, "Nova 27 monitor": 279.00}),
    "C-2002": (0.92, {"Aero 14 laptop": 1149.00, "Nova 27 monitor": 299.00}),
}


def sku_of(item):
    words = [w for w in item.replace("-", " ").split() if w.isalnum()]
    return "-".join(w[:3].upper() for w in words)[:20]


def price_of(item):
    low = item.lower()
    for key in sorted(PRICE, key=len, reverse=True):
        if key in low:
            return PRICE[key]
    return 99.00


CATALOG = {sku_of(i): i for i in ITEMS}


def item_of(sku):
    if sku not in CATALOG:
        raise HTTPException(404, f"no product {sku}")
    return CATALOG[sku]


@app.get("/products")
def find_product(name: str):
    """The catalog entry for a name a customer wrote: the longest product name inside it, else the shortest one that
    contains it ("Aero 14 laptops" and "the Aero 14" both find the Aero 14 laptop, not the Pro)."""
    q = " ".join(name.lower().replace("-", " ").split())
    norm = {sku: " ".join(i.lower().replace("-", " ").split()) for sku, i in CATALOG.items()}
    inside = [sku for sku, n in norm.items() if n in q]
    words = {w.rstrip("s") if len(w) > 3 else w for w in q.split()} - {"the", "a", "an", "our", "my", "your"}
    around = [sku for sku, n in norm.items() if q in n or words <= {w.rstrip("s") if len(w) > 3 else w for w in n.split()}]
    if inside:
        sku = max(inside, key=lambda s: len(norm[s]))
    elif around:
        sku = min(around, key=lambda s: len(norm[s]))
    else:
        raise HTTPException(404, f"no product called {name}")
    return {"sku": sku, "name": CATALOG[sku]}


@app.get("/products/{sku}/price")
def public_price(sku: str, market: str):
    if market not in CURRENCY:
        raise HTTPException(400, f"unknown market {market}")
    return {"sku": sku, "price": f"{price_of(item_of(sku)):.2f}", "currency": CURRENCY[market], "kind": "public"}


@app.get("/users/{email}")
def user(email: str):
    if email.lower() not in USERS:
        raise HTTPException(404, "not a DemoStore Business user")
    company, roles = USERS[email.lower()]
    return {"email": email.lower(), "company_id": company, "company": COMPANIES[company], "roles": roles}


@app.get("/companies/{company_id}/prices/{sku}")
def contract_price(company_id: str, sku: str):
    if company_id not in CONTRACT:
        raise HTTPException(404, f"no company {company_id}")
    item = item_of(sku)
    time.sleep(1.0)   # the contract engine works the price out from the company's price list
    share, fixed = CONTRACT[company_id]
    price = fixed.get(item, round(price_of(item) * share, 2))
    return {"sku": sku, "price": f"{price:.2f}", "currency": "EUR", "kind": "contract", "company_id": company_id}
