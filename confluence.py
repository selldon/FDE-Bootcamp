"""Confluence (B18, IT21): the only code that reads it. GET only, no login, nothing is ever written.

One list call returns every page of space `POL` (see docs/live-shapes.md). `pages()` gives each page as a dict:
id, title, version, market, valid_from, valid_to (a date or None), link, body (Markdown). `FakeConfluence` has the
same interface over a list of such dicts.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

import config

SPACE = "POL"
TIMEOUT = 10
LIST_PATH = "/rest/api/content?" + urllib.parse.urlencode({"spaceKey": SPACE, "type": "page", "limit": 100})


class ConfluenceError(RuntimeError):
    """Confluence could not be read; the caller keeps what it had."""


def get(path):
    """One GET; returns the parsed JSON. Any failure is a `ConfluenceError`."""
    request = urllib.request.Request(config.confluence()["url"] + path, method="GET",
                                     headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ConfluenceError(f"Confluence answered {error.code} to GET {path}") from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ConfluenceError(f"Confluence call GET {path} failed: {error}") from error


def _date(value):
    """A date from `YYYY-MM-DD` (a longer timestamp is cut to its day); empty is None."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise ConfluenceError(f"not a date: {value!r}") from error


def page_from(raw, base_url):
    """One raw API page as our page dict. Missing metadata stays None here; `policy.sections` rejects it."""
    meta = raw.get("metadata") or {}
    link = (raw.get("_links") or {}).get("webui")
    version = raw.get("version")
    body = raw.get("body")
    return {"id": str(raw.get("id", "")), "title": raw.get("title") or "",
            "version": version.get("number") if isinstance(version, dict) else version,
            "market": meta.get("market") or None,
            "valid_from": _date(meta.get("valid_from")), "valid_to": _date(meta.get("valid_to")),
            "link": base_url + link if link else None,
            "body": body if isinstance(body, str) else ""}


def pages(call=get):
    """All pages of space `POL`."""
    reply = call(LIST_PATH)
    results = reply.get("results") if isinstance(reply, dict) else None
    if not isinstance(results, list):
        raise ConfluenceError("Confluence answered without a list of pages")
    base = config.confluence()["url"] if call is get else ""
    return [page_from(raw, base) for raw in results]


class FakeConfluence:
    """The same interface over a list of page dicts (as `pages()` returns them)."""

    def __init__(self, pages_=None):
        self._pages = list(pages_ or [])
        self.fail = None

    def pages(self):
        if self.fail:
            raise self.fail
        return [dict(p) for p in self._pages]
