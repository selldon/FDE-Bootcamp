"""The connection settings of DemoStore's systems, read from the environment."""
import os

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
