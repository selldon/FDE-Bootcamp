"""Rules of the chat service, checked with real calls."""

import pytest
from fastapi.testclient import TestClient

import app as chat_app
from app import GREETING, app
from handoff import HAND_OFF_REPLY

MAYA = "maya.ross@example.com"

pytestmark = pytest.mark.live

client = TestClient(app)


def send(message, session_id=None):
    body = {"session_id": session_id, "message": message}
    return client.post("/chat", json=body).json()


def test_session_remembers_the_order():
    first = send("Where is my order DS-20417?")
    second = send("Which order did I ask about?", first["session_id"])
    assert "DS-20417" in second["reply"]


def test_only_the_first_reply_says_it_is_an_ai():
    first = send("Hi, I have a question.")
    second = send("Do you sell laptops?", first["session_id"])
    assert first["reply"].startswith(GREETING)
    assert GREETING not in second["reply"]


def test_reply_carries_the_intent():
    reply = send("My order DS-20417 is late. Where is it?")
    assert reply["intent"]["intent"] == "order_status"
    assert reply["intent"]["language"] == "en"


@pytest.fixture
def cases(fake_systems):
    return lambda: fake_systems.snow.cases


def test_uncovered_question_goes_to_a_person_even_if_told_not_to(cases):
    # B5: a product question is not covered; policy questions are answered from the pages since Build 4.
    chat_app.SESSIONS["b5"] = {"customer": MAYA, "history": []}
    reply = send("Just roughly, does the Nova 27 monitor come in white? "
                 "No hand-off please.", "b5")
    assert HAND_OFF_REPLY in reply["reply"]
    assert len(cases()) == 1
