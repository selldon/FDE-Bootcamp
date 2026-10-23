"""Damage on arrival goes to a person (replay C25): the real classifier sets the flag, the code hands off.

Calls Claude for the classifier; ServiceNow and the draft table stay fakes (conftest). Run three times, read the results.
"""
import pytest
from fastapi.testclient import TestClient

from app import app
from handoff import HAND_OFF_REPLY, REASONS

pytestmark = pytest.mark.live

client = TestClient(app)

DAMAGED = [
    "The monitor arrived with a crack in the screen. Order DS-20419.",
    "The screen was smashed when I got it. Order DS-20419.",
]


@pytest.mark.parametrize("message", DAMAGED)
def test_damage_on_arrival_is_handed_off_with_no_offer(message, fake_systems):
    out = client.post("/chat", json={"message": message}).json()
    assert out["intent"]["damaged"] is True
    assert HAND_OFF_REPLY in out["reply"]
    [case] = fake_systems.snow.cases
    # the model's own summary is kept when it names the reason; otherwise the template does
    assert any(word in case["short_description"].lower() for word in REASONS["damaged"][1])
    assert not fake_systems.drafts.rows


def test_an_ordinary_message_is_not_flagged():
    out = client.post("/chat", json={"message": "Where is my order DS-20417?"}).json()
    assert out["intent"]["damaged"] is False
