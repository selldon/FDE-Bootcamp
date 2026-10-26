"""The connection settings of DemoStore's systems, read from the environment."""
import os
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()


def setting(name):
    """One setting; a missing one is an error that names it."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set (see .env.example)")
    return value


def ledgerline():
    """The read-only account on the copy of Ledgerline."""
    return {"dsn": setting("LEDGERLINE_DSN"),
            "user": setting("LEDGERLINE_USER"),
            "password": setting("LEDGERLINE_PASSWORD")}


def ledgerline_writer():
    """The writer account: its one use is a return draft into LL_RTN_REQ_STG (Build 3)."""
    return {"dsn": setting("LEDGERLINE_DSN"),
            "user": setting("LEDGERLINE_WRITER_USER"),
            "password": setting("LEDGERLINE_WRITER_PASSWORD")}


def servicenow():
    """ServiceNow: approval tasks and hand-off cases."""
    return {"url": setting("SERVICENOW_URL").rstrip("/"),
            "user": setting("SERVICENOW_USER"),
            "password": setting("SERVICENOW_PASSWORD")}


def confluence():
    """Confluence: the policy space POL, read only."""
    return {"url": setting("CONFLUENCE_URL").rstrip("/")}


def trace_key():
    """The secret of the keyed hash that finds a customer's traces (Build 4, D5)."""
    return setting("TRACE_HMAC_KEY")


def carrier():
    """The carrier's SFTP server."""
    return {"host": setting("CARRIER_HOST"),
            "port": int(setting("CARRIER_PORT")),
            "user": setting("CARRIER_USER"),
            "password": setting("CARRIER_PASSWORD")}


def store_url():
    """Our own PostgreSQL, where the order store lives."""
    return setting("STORE_URL")


def now():
    """The time the product reads as now: the wall clock, unless DEMOSTORE_NOW pins it (an ISO instant with a zone).

    A runner pins it to the day of the sandbox's carrier files, so the freshness checks and the replay give the same
    answers every day. Production sets nothing."""
    pinned = os.environ.get("DEMOSTORE_NOW")
    if not pinned:
        return datetime.now(UTC)
    try:
        moment = datetime.fromisoformat(pinned)
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        raise RuntimeError(f"DEMOSTORE_NOW is {pinned!r}: use an ISO time with a zone, e.g. 2026-10-22T05:00:00+00:00")
    return moment
