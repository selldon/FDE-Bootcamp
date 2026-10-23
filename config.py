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


def carrier():
    """The carrier's SFTP server."""
    return {"host": setting("CARRIER_HOST"),
            "port": int(setting("CARRIER_PORT")),
            "user": setting("CARRIER_USER"),
            "password": setting("CARRIER_PASSWORD")}


def store_url():
    """Our own PostgreSQL, where the order store lives."""
    return setting("STORE_URL")
