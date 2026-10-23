"""Rules of the chat service, checked with real calls."""
from fastapi.testclient import TestClient

from app import GREETING, app

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
