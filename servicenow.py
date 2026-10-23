"""ServiceNow (B15, B16, B17, IT18-IT20): the only code that talks to it, over HTTP with the account from `config.py`.

Two writes and one read, nothing else:
- `create_approval_task(draft)` -> one `sc_task` (`short_description`, `u_draft`). Before it creates, it looks for a task
  with the same `u_draft` (the draft's key) and returns that one, so a retry never makes a second task (IT19).
- `create_case(summary, history, customer)` -> one `interaction` (`short_description`, `u_conversation`). The account
  can create these rows but not read them (D3), so this function never does a GET.
Any failure raises `ServiceNowError`: the caller must tell the customer it was not done. Nothing here moves money.
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

import config

TASKS = "/api/now/table/sc_task"
CASES = "/api/now/table/interaction"
TIMEOUT = 10


class ServiceNowError(RuntimeError):
    """A call to ServiceNow failed; nothing was created that we know of."""


def send(method, path, body=None):
    """One HTTP call with basic auth; returns the parsed JSON. Any failure is a `ServiceNowError`."""
    settings = config.servicenow()
    token = base64.b64encode(f"{settings['user']}:{settings['password']}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(settings["url"] + path, data=data, method=method, headers={
        "Authorization": f"Basic {token}", "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ServiceNowError(f"ServiceNow answered {error.code} to {method} {path}") from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ServiceNowError(f"ServiceNow call {method} {path} failed: {error}") from error


def task_text(draft):
    """The task's `short_description`: the order, the item (line) and the amount, no personal data."""
    return f"Approve refund draft: order {draft['order']}, item {draft['line']}, amount {draft['amount']}"


def _row(reply):
    result = reply.get("result") if isinstance(reply, dict) else None
    if isinstance(result, list):
        result = result[0] if result else None
    return result if isinstance(result, dict) else None


def find_task(key, call=send):
    """The task whose `u_draft` is `key`, or None."""
    query = urllib.parse.urlencode({"sysparm_query": f"u_draft={key}", "sysparm_limit": 1})
    return _row(call("GET", f"{TASKS}?{query}"))


def create_approval_task(draft, call=send):
    """The approval task of a draft (found again if a retry already made it)."""
    existing = find_task(draft["key"], call)
    if existing is not None:
        return existing
    created = _row(call("POST", TASKS, {"short_description": task_text(draft), "u_draft": draft["key"]}))
    if created is None:
        raise ServiceNowError("ServiceNow created no task")
    return created


def create_case(summary, history, customer, call=send):
    """A hand-off case: the checked summary and the chat so far. Create only, never read (D3).

    `customer` is not sent: the account has no field for it, and the chat is the context a person needs.
    """
    body = {"short_description": summary, "u_conversation": json.dumps(list(history))}
    created = _row(call("POST", CASES, body))
    if created is None:
        raise ServiceNowError("ServiceNow created no case")
    return created


class FakeServiceNow:
    """The same two functions over lists; records every call; `fail` makes the next calls raise."""

    def __init__(self):
        self.tasks, self.cases, self.calls = [], [], []
        self.fail = None  # an exception, or None
        self.fail_after_lookup = False  # the lookup works, the create fails

    def call(self, method, path, body=None):
        self.calls.append((method, path))
        if self.fail is not None and not (self.fail_after_lookup and method == "GET"):
            raise self.fail
        if method == "GET":
            key = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)["sysparm_query"][0].split("=", 1)[1]
            return {"result": [t for t in self.tasks if t["u_draft"] == key]}
        row = dict(body, sys_id=f"sys{len(self.tasks) + len(self.cases) + 1}")
        (self.tasks if path == TASKS else self.cases).append(row)
        return {"result": row}

    def create_approval_task(self, draft):
        return create_approval_task(draft, self.call)

    def create_case(self, summary, history, customer):
        return create_case(summary, history, customer, self.call)
