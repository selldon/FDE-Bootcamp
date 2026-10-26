"""Approval tasks in ServiceNow: a person decides on every draft."""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
TASKS = os.environ["SERVICENOW_URL"] + "/api/now/table/sc_task"
AUTH = (os.environ["SERVICENOW_TASKS_USER"],
        os.environ["SERVICENOW_TASKS_PASSWORD"])


def open_task(draft, order, amount):
    """A task for the support team: approve or reject one draft."""
    about = f"Draft {draft}: refund {amount} for {order}"
    task = {"short_description": about, "u_draft": draft,
            "approval": "requested"}
    reply = httpx.post(TASKS, json=task, auth=AUTH)
    reply.raise_for_status()
    return reply.json()["result"]["number"]


def decided_tasks():
    """The tasks a person has approved or rejected."""
    query = {"sysparm_query": "approval!=requested"}
    reply = httpx.get(TASKS, params=query, auth=AUTH)
    reply.raise_for_status()
    return reply.json()["result"]
