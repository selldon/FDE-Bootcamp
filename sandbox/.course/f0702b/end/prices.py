"""Prices from Atlas: a contract price only for a company's buyer."""
import os

import httpx

CACHE = {}


def price(product, session):
    """The customer's price for one product, always from Atlas."""
    atlas = os.environ["ATLAS_URL"]
    found = httpx.get(atlas + "/products", params={"name": product})
    if found.status_code == 404:
        return {"error": "no such product"}
    sku = found.json()["sku"]
    company = session["company"]
    if company and "buyer" in session["roles"]:
        key = (company, sku)
        if key not in CACHE:
            url = f"{atlas}/companies/{company}/prices/{sku}"
            CACHE[key] = httpx.get(url).json()
        return CACHE[key]
    url = f"{atlas}/products/{sku}/price?market={session['market']}"
    return httpx.get(url).json()
