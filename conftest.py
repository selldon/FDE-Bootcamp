"""A scripted fake model: canned responses instead of calls to Claude."""
import csv
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import llm
import store
import tools

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def seed_store(db):
    """Fill a FakeStore from the old fakes in data/: the only place that reads them."""
    with open("data/orders.json") as f:
        orders = json.load(f)
    with open("data/carrier.csv") as f:
        news = {r["tracking"]: r for r in csv.DictReader(f)}
    parcels = [{"tracking": t, "order_no": o["number"], "carrier_status": news[t]["status"],
                "place": news[t]["place"], "news_date": news[t]["date"]}
               for o in orders for t in o["tracking"] if t in news]
    db.save(orders, parcels)
    return db


@pytest.fixture(autouse=True)
def order_store(monkeypatch):
    """Every test reads a FakeStore seeded from the fakes, at a fixed time."""
    db = seed_store(store.FakeStore())
    monkeypatch.setattr(tools, "_store", db)
    monkeypatch.setattr(tools, "clock", lambda: NOW)
    return db


def text(content):
    return SimpleNamespace(type="text", text=content)


def tool_use(name, args, id="toolu_1"):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=args)


def reply(*blocks):
    stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class FakeModel:
    """Returns the canned responses in order; keeps what it was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@pytest.fixture
def fake_model(monkeypatch):
    def install(*responses):
        model = FakeModel(responses)
        monkeypatch.setattr(llm.client, "messages",
                            SimpleNamespace(create=model.create))
        return model
    return install
