"""Fast tests of the go-live simulator: a fake model, fake systems and a FakeGoLiveStore. No Claude, no container."""
import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as app_module
import golive_sim as sim
import llm
import verify
from conftest import reply, text, tool_use
from golive import ASSISTANT, CONTROL

SHARE = 0.2
client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, fake_golive):
    monkeypatch.setattr(verify, "_default", verify.Verifier(outbox=str(tmp_path / "outbox.jsonl")))
    monkeypatch.setattr(app_module, "SESSIONS", {})
    fake_golive.set_settings(share=SHARE)
    return tmp_path


@pytest.fixture
def assumptions():
    a = sim.load_assumptions()
    return a | {"visitors_per_day": 40, "control_repeat_rate": 0.1, "control_repeat_rate_n": 100}


@pytest.fixture
def world():
    return sim.load_truth() + (sim.load_profiles(),)  # orders, truth, profiles


class Gateway:
    """The chat service in memory (TestClient), the one-time code read from the outbox like the HTTP gateway does."""

    def __init__(self, outbox):
        self.outbox = outbox

    def chat(self, body):
        return client.post("/chat", json=body).json()

    def verify(self, email):
        sid = client.post("/verify/start", json={"email": email}).json()["session_id"]
        code = sim.HttpGateway.code_for(SimpleNamespace(outbox=self.outbox), email)
        client.post("/verify/check", json={"session_id": sid, "email": email, "code": code})
        return sid


def intent_json(message):
    low = message.lower()
    if "return the" in low:
        intent = "return_request"
    elif "warranty" in low or "how long do i have" in low:
        intent = "policy_question"
    elif "ds-" in low or "order" in low:
        intent = "order_status"
    else:
        intent = "other"
    return json.dumps({"summary": intent, "intent": intent, "order_number": None, "needs_human": False,
                       "damaged": False, "language": "en"})


def install_model(monkeypatch, says):
    """A model that classifies by keyword and, for an order, calls find_order and words the result with `says`."""
    seen = {"calls": 0}

    def create(**kwargs):
        seen["calls"] += 1
        if "tools" not in kwargs:
            return reply(text(intent_json(kwargs["messages"][0]["content"].rpartition("Message: ")[2])))
        messages = kwargs["messages"]
        last = messages[-1]["content"]
        if isinstance(last, str):
            numbers = [n for m in messages if isinstance(m["content"], str) for n in re.findall(r"DS-\d+", m["content"])]
            if not numbers:
                return reply(text("Which order do you mean?"))
            return reply(tool_use("find_order", {"number": numbers[-1]}))
        result = json.loads(re.search(r"\{.*\}", last[0]["content"], re.DOTALL).group(0))
        return reply(text(says(result)))

    monkeypatch.setattr(llm.client, "messages", SimpleNamespace(create=create))
    return seen


def truthful(result):
    if "error" in result:
        return "I could not find that order."
    return f"Your order is {result['status']}. It is due on {result['promised']}."


def wrong(result):
    return "Good news: your order has been delivered."  # a status given as fact, whatever the truth


# ---- the traffic ------------------------------------------------------------------------------------------------

def test_same_seed_gives_the_same_traffic_and_another_seed_another(assumptions, world):
    orders, _, profiles = world
    day = lambda seed: sim.make_visitors(3, assumptions, orders, profiles, SHARE, seed)
    assert day(7) == day(7)
    assert day(7) != day(8)
    assert [v.id for v in day(7)] != [v.id for v in sim.make_visitors(4, assumptions, orders, profiles, SHARE, 7)]


def test_a_visitor_has_a_question_and_one_to_three_followups(assumptions, world):
    orders, _, profiles = world
    visitors = [v for d in range(1, 6) for v in sim.make_visitors(d, assumptions, orders, profiles, SHARE)]
    status = [v for v in visitors if v.intent == "order_status" and v.kind == "plain"]
    assert status and all(2 <= v.turns <= 4 for v in status)
    assert {v.group for v in visitors} == {ASSISTANT, CONTROL}
    assert len({v.id for v in visitors}) == len(visitors)


def test_the_plan_is_the_same_each_time_and_the_default_traffic_fits_the_cap():
    a = sim.load_assumptions()
    p = sim.plan(a, list(range(1, a["days"] + 1)))
    assert p == sim.plan(a, list(range(1, a["days"] + 1)))
    assert p["stopped_on"] is None and p["assistant"] <= a["assistant_cap"] == 150


# ---- the cap ----------------------------------------------------------------------------------------------------

def test_the_cap_holds_and_the_run_says_so(assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)
    a = assumptions | {"assistant_cap": 12}
    out, said = isolated / "out.jsonl", []
    sim.run([1, 2, 3, 4, 5], a, Gateway(isolated / "outbox.jsonl"), fake_golive, out, SHARE, orders, truth, profiles,
            said.append)
    rows = sim.read_out(out)
    assert sum(r["group"] == ASSISTANT for r in rows) <= 12
    assert any(m.startswith("STOPPED") and "cap of 12" in m for m in said)
    ran = sorted({r["sim_day"] for r in rows})
    assert ran == list(range(1, len(ran) + 1)) and len(ran) < 5  # whole days only, then it stops
    assert sim.plan(a, [1, 2, 3, 4, 5], SHARE, orders=orders, profiles=profiles)["stopped_on"] == len(ran) + 1


def test_the_cap_counts_the_conversations_already_in_the_file(assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)
    a = assumptions | {"assistant_cap": 25}
    out, said = isolated / "out.jsonl", []
    gateway = Gateway(isolated / "outbox.jsonl")
    sim.run([1], a, gateway, fake_golive, out, SHARE, orders, truth, profiles, said.append)
    sim.run([2, 3, 4, 5], a, gateway, fake_golive, out, SHARE, orders, truth, profiles, said.append)
    assert sum(r["group"] == ASSISTANT for r in sim.read_out(out)) <= 25
    with pytest.raises(SystemExit, match="already"):
        sim.run([1], a, gateway, fake_golive, out, SHARE, orders, truth, profiles, said.append)


# ---- the scoring ------------------------------------------------------------------------------------------------

TRUTH = {"status": "on_the_way", "dates": ["2026-10-21", "2026-10-24"], "customer": "x"}


@pytest.mark.parametrize("reply_text, is_wrong", [
    ("Your parcel is in transit and should arrive on 24 October.", False),
    ("It is on its way, due 2026-10-24.", False),
    ("The last scan was on October 21 in Leeds.", False),
    ("Your parcel has been delivered.", True),  # the status differs from the truth
    ("Your order is on its way and will arrive on 25 October.", True),  # the date differs
    ("It will be delivered on 24 October.", False),  # a promise, not a claim of delivery
    ("It is still processing.", True),
    ("The carrier's news is old, so I will not give a date. I can pass you to a person.", False),
    ("Your parcel has been delivered, but the news may have changed.", False),  # hedged
    ("Which order do you mean?", False),
])
def test_a_wrong_status_is_counted_against_the_truth(reply_text, is_wrong):
    assert sim.score_reply(reply_text, TRUTH)["wrong"] is is_wrong


def test_truth_follows_the_carrier_and_a_delivered_parcel_makes_the_order_delivered():
    orders = [{"number": "DS-1", "customer": "a", "status": "shipped", "promised": "2026-10-19", "tracking": ["T1"]},
              {"number": "DS-2", "customer": "b", "status": "shipped", "promised": "2026-10-20", "tracking": ["T2"]},
              {"number": "DS-3", "customer": "c", "status": "partly shipped", "promised": "2026-10-24",
               "tracking": ["T3", "T4"]}]
    carrier = [{"tracking": "T1", "status": "delivered", "date": "2026-10-21"},
               {"tracking": "T2", "status": "in transit", "date": "2026-10-21"}]
    truth = sim.build_truth(orders, carrier)
    assert truth["DS-1"]["status"] == "delivered" and truth["DS-2"]["status"] == "on_the_way"
    assert truth["DS-3"]["status"] == "partly"
    assert truth["DS-2"]["dates"] == ["2026-10-20", "2026-10-21"]
    assert sim.score_reply("Your order is delivered.", truth["DS-3"])["wrong"]


def test_run_counts_a_model_that_states_a_wrong_status_and_not_one_that_tells_the_truth(
        assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    a = assumptions | {"assistant_cap": 150}
    install_model(monkeypatch, wrong)
    bad = sim.run_day(1, sim.make_visitors(1, a, orders, profiles, SHARE), Gateway(isolated / "outbox.jsonl"),
                      fake_golive, truth, a, a["seed"])
    flagged = [r for r in bad if r["confidently_wrong"]]
    delivered = {n for n, t in truth.items() if t["status"] == "delivered"}
    assert flagged and all(r["group"] == ASSISTANT and r["order"] not in delivered for r in flagged)
    assert not [r for r in bad if r["group"] == CONTROL and r["confidently_wrong"]]


def test_a_truthful_model_gets_no_confidently_wrong(assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)
    rows = sim.run_day(1, sim.make_visitors(1, assumptions, orders, profiles, SHARE),
                       Gateway(isolated / "outbox.jsonl"), fake_golive, truth, assumptions, assumptions["seed"])
    assert [r for r in rows if r["group"] == ASSISTANT and r["intent"] == "order_status"]
    assert not any(r["confidently_wrong"] for r in rows)


# ---- the labels -------------------------------------------------------------------------------------------------

def test_every_row_is_labelled_simulated_in_the_file_and_in_the_service_table(
        assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)
    out = isolated / "out.jsonl"
    sim.run([1, 2], assumptions, Gateway(isolated / "outbox.jsonl"), fake_golive, out, SHARE, orders, truth, profiles,
            lambda m: None)
    rows = sim.read_out(out)
    assert rows and all(r["simulated"] is True for r in rows)
    stored = fake_golive.chats()
    assert stored and all(r["simulated"] and r["sim_day"] in (1, 2) for r in stored)
    assert {r["chat_id"] for r in rows} == {r["chat_id"] for r in stored}  # the file joins to the table by chat id
    assert {r["group"] for r in rows} == {ASSISTANT, CONTROL}
    assert all(1 <= r["rating"] <= 5 for r in rows)


def test_the_same_seed_gives_the_same_rows_twice(assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)

    def one_day():
        rows = sim.run_day(2, sim.make_visitors(2, assumptions, orders, profiles, SHARE),
                           Gateway(isolated / "outbox.jsonl"), fake_golive, truth, assumptions, assumptions["seed"])
        return [{k: v for k, v in r.items() if k not in ("chat_id", "model_cost")} for r in rows]

    assert one_day() == one_day()


def test_a_run_needs_the_repeat_rate_computed_first(assumptions, isolated, fake_golive):
    with pytest.raises(SystemExit, match="refresh-repeat"):
        sim.run([1], assumptions | {"control_repeat_rate": None}, None, fake_golive, isolated / "o.jsonl")


# ---- the repeat contacts and the dry run ----------------------------------------------------------------------

def test_repeat_rate_from_old_chats_counts_a_second_chat_inside_the_window():
    chat = lambda who, when: {"opened_for": who, "opened_at": when}
    old = [chat("a", "2026-04-01 08:00:00"), chat("a", "2026-04-07 08:00:00"),  # 6 days: a repeat
           chat("b", "2026-04-01 08:00:00"), chat("b", "2026-04-09 08:00:01"),  # 8 days: not
           chat("c", "2026-04-01 08:00:00")]
    assert sim.repeat_rate(old, 7) == (1 / 5, 5)
    assert sim.repeat_rate([], 7) == (None, 0)


def test_dry_run_needs_no_claude_and_writes_nothing(isolated, monkeypatch, capsys):
    def no_call(**kwargs):
        raise AssertionError("the dry run must not call Claude")

    monkeypatch.setattr(llm.client, "messages", SimpleNamespace(create=no_call))
    out = isolated / "never.jsonl"
    assert sim.main(["--dry-run", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "SIMULATED" in printed and "expected model calls" in printed and "cost estimate: $" in printed
    assert not out.exists() and not list(isolated.glob("*.jsonl"))
