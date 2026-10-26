"""A scripted fake model: canned responses instead of calls to Claude."""
import csv
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import drafts
import ledgerline
import llm
import refunds
import servicenow
import store
import tools
import traces

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


SKU_OF = {"Aero 14 laptop": "AER-14-LAP", "Aero 14 Pro laptop": "AER-14-PRO-LAP", "Desk speakers S2": "DES-SPE-S2",
          "Docking station D2": "DOC-STA-D2", "Gaming headset H3": "GAM-HEA-H3", "Inkjet printer P2": "INK-PRI-P2",
          "Keyboard K2": "KEY-K2", "Laser printer P5": "LAS-PRI-P5", "Mouse M3": "MOU-M3",
          "Nova 24 monitor": "NOV-24-MON", "Nova 27 monitor": "NOV-27-MON", "Nova 32 monitor": "NOV-32-MON",
          "Power supply 850 W": "POW-SUP-850-W", "Smart speaker S1": "SMA-SPE-S1", "SSD 1 TB": "SSD-1-TB",
          "SSD 2 TB": "SSD-2-TB", "Vento mini PC": "VEN-MIN-PC", "Volt 8 graphics card": "VOL-8-GRA-CAR",
          "Webcam W1": "WEB-W1", "Wi-Fi router R6": "WI-FI-ROU-R6"}


def seed_ledgerline(fake):
    """Fill a FakeLedgerline from data/orders.json plus made-up prices: the only place that does it.

    One line per item, 100.00 per unit and 20.00 tax, one unit. The parcels go to the lines pairwise;
    when there are fewer parcels than items, every line shares the order's parcels.
    """
    from decimal import Decimal

    import kinds
    import ledgerline
    with open("data/orders.json") as f:
        orders = json.load(f)
    for o in orders:
        pairwise = len(o["tracking"]) == len(o["items"])
        lines = [{"line": i + 1, "sku": SKU_OF[item], "item": item, "kind": kinds.kind(SKU_OF[item]),
                  "quantity": 1, "unit_price": Decimal("100.00"), "tax": Decimal("20.00"),
                  "tracking": [o["tracking"][i]] if pairwise else list(o["tracking"])}
                 for i, item in enumerate(o["items"])]
        fake.orders[o["number"]] = {"number": o["number"], "customer": o["customer"], "market": o["market"],
                                    "currency": "EUR", "customer_type": "consumer", "lines": lines}
    assert isinstance(fake, ledgerline.FakeLedgerline)
    return fake


@pytest.fixture(autouse=True)
def fake_systems(monkeypatch):
    """Every test reads Ledgerline, writes drafts and creates tasks in fakes: no real system is ever reached."""
    ledger = seed_ledgerline(ledgerline.FakeLedgerline())
    systems = SimpleNamespace(ledger=ledger, drafts=drafts.FakeDrafts(), snow=servicenow.FakeServiceNow())
    monkeypatch.setattr(refunds, "_ledgerline", ledger)
    monkeypatch.setattr(refunds, "_drafts", systems.drafts)
    monkeypatch.setattr(refunds, "_servicenow", systems.snow)
    return systems


@pytest.fixture(autouse=True)
def fake_traces(monkeypatch):
    """Every test records model calls into a FakeTraces: the real table is never reached."""
    fake = traces.FakeTraces()
    monkeypatch.setattr(traces, "_sink", fake)
    monkeypatch.setattr(traces, "failures", 0)
    return fake


@pytest.fixture(autouse=True)
def fake_policy(monkeypatch):
    """Every test searches a FakeIndex with a FakeEmbedder: the real index and the embedding model are never reached."""
    import embedder
    import policy_answer
    import policy_index
    fake = SimpleNamespace(index=policy_index.FakeIndex(), embedder=embedder.FakeEmbedder())
    monkeypatch.setattr(policy_answer, "_index", fake.index)
    monkeypatch.setattr(policy_answer, "_embedder", fake.embedder)
    return fake


def unwrap(content):
    """The tool result a model was sent: the JSON inside the data block (IT21, IT23)."""
    import agent
    assert content.startswith(agent.DATA_OPEN) and content.endswith(agent.DATA_CLOSE), "a tool result outside a data block"
    return json.loads(content[len(agent.DATA_OPEN):-len(agent.DATA_CLOSE)])
