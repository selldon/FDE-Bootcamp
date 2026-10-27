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


# ---- week one, corrected: product names are not dates, the truth is the night the service loads, labels reach the table ----

@pytest.mark.parametrize("sentence, dates", [
    ("The Nova 32 monitor and two Nova 24 monitors, the Nova 27 too.", set()),  # "Nov" + "a" + a number was read as a date
    ("The Nova 32 monitor was delivered on 22 October 2026.", {"2026-10-22"}),
    ("Out for delivery on Oct 22 and promised for 24th October.", {"2026-10-22", "2026-10-24"}),
    ("Sent on March 5, back by Sept. 9, 2026.", {"2026-03-05", "2026-09-09"}),
    ("The carrier's last update is from 2026-10-22.", {"2026-10-22"}),
])
def test_a_product_name_is_not_read_as_a_date(sentence, dates):
    assert sim.dates_in(sentence, "2026") == dates


def write_night(folder, day, header, lines):
    (folder / f"carrier-{day}.csv").write_bytes((header + "\n" + "\n".join(lines) + "\n").encode("cp1252"))


def test_the_truth_is_built_from_the_newest_carrier_night_the_file_the_service_loads(tmp_path):
    write_night(tmp_path, "2026-10-21", "tracking,status,place,date", ["T1,in transit,Leeds depot,2026-10-21"])
    write_night(tmp_path, "2026-10-22", "tracking,status,pickup_point,place,date",
                ["T1,out for delivery,,Düsseldorf depot,2026-10-22"])  # another column set, and a cp1252 letter
    name, rows = sim.newest_carrier(tmp_path)
    assert name == "carrier-2026-10-22.csv"
    assert rows[0]["status"] == "out for delivery" and rows[0]["date"] == "2026-10-22"  # a string, as build_truth wants
    orders = [{"number": "DS-1", "customer": "a", "status": "shipped", "promised": "2026-10-23", "tracking": ["T1"]}]
    truth = sim.build_truth(orders, rows)
    assert truth["DS-1"]["dates"] == ["2026-10-22", "2026-10-23"]


def test_an_empty_carrier_folder_is_an_error_not_an_empty_truth(tmp_path):
    with pytest.raises(SystemExit, match="carrier"):
        sim.newest_carrier(tmp_path)


def test_the_default_truth_is_the_night_of_the_22nd():
    _, truth = sim.load_truth()
    assert "2026-10-22" in truth["DS-20476"]["dates"] and "2026-10-21" not in truth["DS-20476"]["dates"]


PARTLY = [{"number": "DS-3", "customer": "c", "status": "partly shipped", "promised": "2026-10-24",
           "tracking": ["T3", "T4"]}]


def partly_truth(*statuses):
    carrier = [{"tracking": t, "status": s, "date": "2026-10-22"} for t, s in zip(("T3", "T4"), statuses, strict=False)]
    return sim.build_truth(PARTLY, carrier)["DS-3"]


@pytest.mark.parametrize("statuses, reply_text, is_wrong", [
    # every fact matches the carrier, and the reply names that the order still says part shipped: right
    (("delivered", "delivered"), 'The carrier shows both parcels delivered on 2026-10-22. The order still says "part shipped".',
     False),
    (("delivered", "delivered"), "Both parcels were delivered on 2026-10-22, although the order is still partly shipped.",
     False),
    # the mismatch is hidden: wrong, as before
    (("delivered", "delivered"), "Your parcels have been delivered.", True),
    # the carrier does not say both are delivered: the claim is wrong even if the mismatch is named
    (("delivered", "in transit"), 'Both parcels have been delivered. The order status says "part shipped".', True),
    # a wrong date still counts
    (("delivered", "delivered"), 'Both parcels were delivered on 2026-10-19. The order says "part shipped".', True),
])
def test_a_partly_shipped_reply_is_right_when_its_facts_match_and_it_names_the_mismatch(statuses, reply_text, is_wrong):
    assert sim.score_reply(reply_text, partly_truth(*statuses))["wrong"] is is_wrong


def test_a_run_writes_the_labels_into_the_table_but_not_a_repeat_contact(
        assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)
    out = isolated / "out.jsonl"
    sim.run([1], assumptions, Gateway(isolated / "outbox.jsonl"), fake_golive, out, SHARE, orders, truth, profiles,
            lambda m: None)
    by_id = {r["chat_id"]: r for r in sim.read_out(out)}
    stored = fake_golive.chats()
    assert stored and all(c["rating"] == by_id[c["chat_id"]]["rating"] for c in stored)
    control = [c for c in stored if c["group_name"] == CONTROL]
    assert control and all(c["outcome"] == by_id[c["chat_id"]]["outcome"] != "queued" for c in control)
    assert any(c["outcome"] == "resolved" for c in control)  # the rule's outcome, not "waiting in the queue"
    assert all(c["needs_person"] == by_id[c["chat_id"]]["needs_person"] for c in stored)
    assert all(c["repeat_contact"] is None for c in stored)  # not measured: nothing is written for it


def test_rescoring_changes_the_labels_from_the_replies_and_keeps_the_old_file_aside(
        assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)
    out = isolated / "out.jsonl"
    sim.run([1], assumptions, Gateway(isolated / "outbox.jsonl"), fake_golive, out, SHARE, orders, truth, profiles,
            lambda m: None)
    assert not any(r["confidently_wrong"] for r in sim.read_out(out))
    chats = {c["chat_id"] for c in fake_golive.chats() if c["group_name"] == ASSISTANT and c["intent"] == "order_status"}
    assert chats
    new = sim.rescore(assumptions, fake_golive, truth, lambda sid: ["Good news: your order has been delivered."],
                      out, orders, profiles, SHARE)
    flagged = {r["chat_id"] for r in new if r["confidently_wrong"]}
    delivered = {n for n, t in truth.items() if t["status"] == "delivered"}
    assert flagged and all(r["order"] not in delivered for r in new if r["chat_id"] in flagged)
    assert {c["chat_id"] for c in fake_golive.chats() if c["confidently_wrong"]} == flagged  # the table follows
    assert [r for r in new if r["group"] == CONTROL] == [r for r in sim.read_out(out) if r["group"] == CONTROL]
    kept = sim.replace_out(out, new)
    assert kept.exists() and not any(r["confidently_wrong"] for r in sim.read_out(kept))  # the old rows, untouched
    assert {r["chat_id"] for r in sim.read_out(out) if r["confidently_wrong"]} == flagged
    second = sim.replace_out(out, new)  # a second rescore keeps its own copy; the first is never overwritten
    assert second != kept and kept.exists()


def test_rescoring_refuses_a_chat_with_no_replies_instead_of_scoring_it_as_right(
        assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)
    out = isolated / "out.jsonl"
    sim.run([1], assumptions, Gateway(isolated / "outbox.jsonl"), fake_golive, out, SHARE, orders, truth, profiles,
            lambda m: None)
    with pytest.raises(SystemExit, match="no replies"):
        sim.rescore(assumptions, fake_golive, truth, lambda sid: [], out, orders, profiles, SHARE)


# ---- a negated status is not a claim ("It isn't still on its way") ---------------------------------------------------

DELIVERED = {"status": "delivered", "dates": ["2026-10-14"], "customer": "x", "all_delivered": True}


@pytest.mark.parametrize("reply_text, claims, is_wrong", [
    # the two replies of week two that were flagged because "on its way" was read through the "n't"
    ("It shouldn't still be on its way. The carrier shows order DS-20570 as already delivered, on 2026-10-14.",
     [], False),
    ("Your order isn't still on its way. The carrier shows it as delivered to your front door on 2026-10-14.",
     [], False),
    ("It is not in transit any more; it was delivered on 2026-10-14.", ["delivered"], False),
    ("It is no longer on the way: delivered on 2026-10-14.", ["delivered"], False),
    # a negation never hides a claim that is really made
    ("I can't find a later scan, but it is on its way.", ["on_the_way"], True),
    ("It is not delivered yet; it is on its way.", ["on_the_way"], True),
    ("It isn't late. It has been shipped.", ["on_the_way"], True),
    ("The order is on its way, not delivered.", ["on_the_way"], True),
])
def test_a_negated_status_is_not_a_claim_and_a_negation_never_hides_one(reply_text, claims, is_wrong):
    score = sim.score_reply(reply_text, DELIVERED)
    assert (score["claims"], score["wrong"]) == (claims, is_wrong)


def test_the_partly_shipped_rule_is_unchanged_the_hidden_mismatch_of_week_two_is_still_wrong():
    day_8 = ("Order DS-20468 shipped in two parcels, and the carrier shows both as delivered to your front door.\n\n"
             "- The first parcel was delivered on 2026-10-20.\n- The second parcel was delivered on 2026-10-22.\n\n"
             "Both arrived before the promised date of 2026-10-24. Please check around the door and with neighbors.")
    truth = partly_truth("delivered", "delivered")
    truth["dates"] = ["2026-10-20", "2026-10-22", "2026-10-24"]
    assert sim.score_reply(day_8, truth)["wrong"] is True  # right facts, mismatch not named: wrong, as written
    named = day_8 + ' The order status still says "part shipped".'
    assert sim.score_reply(named, truth)["wrong"] is False


def test_a_second_rescore_sets_the_log_aside_again_and_never_overwrites_the_first_copy(
        assumptions, world, isolated, fake_golive, monkeypatch):
    orders, truth, profiles = world
    install_model(monkeypatch, truthful)
    out = isolated / "out.jsonl"
    sim.run([1], assumptions, Gateway(isolated / "outbox.jsonl"), fake_golive, out, SHARE, orders, truth, profiles,
            lambda m: None)
    original = out.read_text()
    first = sim.replace_out(out, sim.read_out(out)[:3])
    second = sim.replace_out(out, sim.read_out(out)[:1])
    assert first != second and first.read_text() == original and len(sim.read_out(second)) == 3
    assert len(sim.read_out(out)) == 1
