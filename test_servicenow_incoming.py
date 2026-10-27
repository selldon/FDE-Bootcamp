"""The ServiceNow stand-in's live chats (shadow mode): a restarted stand-in must not hand out a number twice.

A real ServiceNow never reuses a chat number, and the worker stores a chat once per number. The stand-in once counted from
the start of its process, so every restart (a deploy recreates it) began again at IMS0005001 and the worker dropped the
chats that carried a number it already had."""
import importlib.util
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest

SIM = Path(__file__).parent / "sandbox" / "systems" / "servicenow" / "sim.py"
T0 = datetime(2026, 10, 27, 3, 5, 0)


@pytest.fixture
def sim(monkeypatch):
    monkeypatch.setenv("SNOW_INCOMING_EVERY", "120")
    spec = importlib.util.spec_from_file_location("servicenow_sim", SIM)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def minutes(n):
    return T0 + timedelta(minutes=n)


def test_a_restarted_stand_in_never_repeats_a_number(sim):
    before = sim.incoming(now=minutes(10), started=T0)           # the first container
    after = sim.incoming(now=minutes(30), started=minutes(13))   # recreated by a deploy at minute 13
    assert before and after
    assert {c["number"] for c in before}.isdisjoint(c["number"] for c in after)
    assert min(c["number"] for c in after) > max(c["number"] for c in before)
    assert len({c["number"] for c in before + after}) == len(before + after)


def test_two_runs_that_both_see_a_chat_give_it_the_same_number_and_time(sim):
    one = {c["number"]: c for c in sim.incoming(now=minutes(20), started=T0)}
    two = {c["number"]: c for c in sim.incoming(now=minutes(20), started=minutes(3))}
    shared = set(one) & set(two)
    assert shared
    for number in shared:
        assert one[number]["opened_at"] == two[number]["opened_at"]
        assert one[number]["transcript"].split("\n")[0] == two[number]["transcript"].split("\n")[0]


def test_a_chat_opens_every_interval_after_the_start(sim):
    chats = sim.incoming(now=minutes(10), started=T0)
    opened = [datetime.strptime(c["opened_at"], "%Y-%m-%d %H:%M:%S") for c in chats]
    assert len(chats) == 5 and all(t > T0 for t in opened)
    assert [b - a for a, b in pairwise(opened)] == [timedelta(seconds=120)] * 4
