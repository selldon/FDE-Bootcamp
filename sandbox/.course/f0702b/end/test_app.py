"""Rules of the chat service, checked with real calls."""
import os
import re

import httpx
from fastapi.testclient import TestClient

from app import GREETING, app

client = TestClient(app)
QUESTION = "What is our price for the Aero 14 laptop?"


def send(message, session_id=None):
    body = {"session_id": session_id, "message": message}
    return client.post("/chat", json=body).json()


def verified(order, email):
    """Ask about an order, then type the code from the email."""
    first = send(f"Where is my order {order}?")
    found = httpx.get(os.environ["MAILPIT_URL"] + "/api/v1/search",
                      params={"query": "to:" + email}).json()
    code = re.search(r"\d{6}", found["messages"][0]["Snippet"])[0]
    body = {"session_id": first["session_id"], "code": code}
    assert client.post("/verify", json=body).json()["verified"]
    return first["session_id"]


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


def test_a_stranger_gets_no_parcel_status():
    reply = send("Where is my parcel EP-7718204?")
    assert "Leeds" not in reply["reply"]


def test_the_code_from_the_email_unlocks_the_order():
    session_id = verified("DS-20417", "maya.ross@example.com")
    reply = send("So where is it now?", session_id)
    assert "Leeds" in reply["reply"]


def test_an_approver_gets_the_public_price():
    sara = verified("DS-20402", "sara.conti@example.com")
    reply = send(QUESTION, sara)["reply"]
    assert "1,299" in reply


def test_each_buyer_gets_the_price_of_their_company():
    ines = verified("DS-20481", "ines.dubois@example.com")
    jonas = verified("DS-20447", "jonas.weber@example.com")
    ines_reply = send(QUESTION, ines)["reply"]
    jonas_reply = send(QUESTION, jonas)["reply"]
    assert "1,099" in ines_reply
    assert "1,149" in jonas_reply
