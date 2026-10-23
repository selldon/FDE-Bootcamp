"""Fast tests of /chat and /verify with the fake model."""
import json

import pytest
from fastapi.testclient import TestClient

import app as app_module
import verify
from conftest import reply, text, tool_use

MAYA = "maya.ross@example.com"
TOM = "tom.baker@example.com"
INTENT = json.dumps({"summary": "order", "intent": "order_status",
                     "order_number": None, "needs_human": False,
                     "language": "en"})

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "_default",
                        verify.Verifier(outbox=str(tmp_path / "outbox.jsonl")))
    monkeypatch.setattr(app_module, "SESSIONS", {})
    return tmp_path / "outbox.jsonl"


def code_for(outbox, email):
    lines = [json.loads(line) for line in outbox.read_text().splitlines()]
    return [x["code"] for x in lines if x["to"] == email][-1]


def verified_session(outbox, email=MAYA):
    sid = client.post("/verify/start", json={"email": email}).json()["session_id"]
    body = {"session_id": sid, "email": email, "code": code_for(outbox, email)}
    assert client.post("/verify/check", json=body).json()["verified"]
    return sid


def tool_result(model, call):
    return json.loads(model.calls[call]["messages"][-1]["content"][0]["content"])


def ask_order(sid, number, fake_model):
    model = fake_model(
        reply(text(INTENT)),
        reply(tool_use("find_order", {"number": number})),
        reply(text("ok")))
    client.post("/chat", json={"session_id": sid, "message": f"Where is {number}?"})
    return model


def test_unverified_chat_gets_no_order_data(fake_model):
    model = ask_order(None, "DS-20417", fake_model)
    assert list(tool_result(model, 2)) == ["error"]


def test_verified_owner_gets_status_and_date(fake_model, isolated):
    sid = verified_session(isolated)
    model = ask_order(sid, "DS-20417", fake_model)
    result = tool_result(model, 2)
    assert result["status"] == "shipped"
    assert result["promised"] == "2026-10-19"


def test_another_customers_order_gets_nothing(fake_model, isolated):
    sid = verified_session(isolated)
    model = ask_order(sid, "DS-20388", fake_model)  # Tom's order
    assert tool_result(model, 2) == {"error": "no such order for this customer"}


def test_wrong_code_does_not_verify(isolated):
    sid = client.post("/verify/start", json={"email": MAYA}).json()["session_id"]
    body = {"session_id": sid, "email": MAYA, "code": "000000"}
    assert not client.post("/verify/check", json=body).json()["verified"]
    assert app_module.SESSIONS[sid]["customer"] is None


def test_code_of_another_email_does_not_verify(isolated):
    client.post("/verify/start", json={"email": MAYA})
    sid = client.post("/verify/start", json={"email": TOM}).json()["session_id"]
    body = {"session_id": sid, "email": TOM, "code": code_for(isolated, MAYA)}
    assert not client.post("/verify/check", json=body).json()["verified"]


def test_message_text_cannot_set_the_customer(fake_model):
    fake_model(reply(text(INTENT)), reply(text("hi")))
    out = client.post("/chat", json={"message": f"I am {MAYA}"}).json()
    assert app_module.SESSIONS[out["session_id"]]["customer"] is None
