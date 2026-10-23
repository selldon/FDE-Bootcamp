"""The one-time code: sent only to a customer with orders, valid 10 minutes, 3 tries."""
import hmac
import json
import secrets
import time
from collections.abc import Callable

from tools import ORDERS

TTL_SECONDS = 600
MAX_TRIES = 3


class Verifier:
    def __init__(self, clock: Callable[[], float] = time.time,
                 outbox: str = "data/outbox.jsonl"):
        self.clock = clock
        self.outbox = outbox
        self.pending: dict[str, dict] = {}

    def start(self, email: str) -> dict:
        """Same answer for every email: nothing tells who is a customer."""
        email = email.strip().lower()
        if any(order["customer"] == email for order in ORDERS):
            code = f"{secrets.randbelow(10**6):06d}"
            self.pending[email] = {
                "code": code, "expires": self.clock() + TTL_SECONDS, "tries": 0}
            with open(self.outbox, "a") as f:
                f.write(json.dumps({"to": email, "code": code}) + "\n")
        return {"sent": True}

    def check(self, email: str, code: str) -> bool:
        email = email.strip().lower()
        entry = self.pending.get(email)
        if entry is None:
            return False
        if self.clock() > entry["expires"] or entry["tries"] >= MAX_TRIES:
            del self.pending[email]
            return False
        entry["tries"] += 1
        if hmac.compare_digest(entry["code"], str(code).strip()):
            del self.pending[email]
            return True
        if entry["tries"] >= MAX_TRIES:
            del self.pending[email]
        return False


_default = Verifier()


def start(email: str) -> dict:
    return _default.start(email)


def check(email: str, code: str) -> bool:
    return _default.check(email, code)
