"""Fast tests of /chat and /verify with the fake model."""
import json

import pytest
from fastapi.testclient import TestClient

import app as app_module
import verify
from conftest import reply, text, tool_use
from handoff import HAND_OFF_REPLY

MAYA = "maya.ross@example.com"
TOM = "tom.baker@example.com"
INTENT = json.dumps({"summary": "order", "intent": "order_status",
                     "order_number": None, "needs_human": False, "damaged": False,
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


def intent(**fields):
    base = {"summary": "wants something", "intent": "order_status",
            "order_number": None, "needs_human": False, "damaged": False, "language": "en"}
    return {**base, **fields}


@pytest.mark.parametrize("fields", [
    {"needs_human": True},
    {"intent": "product_question"},
])
def test_classifier_hand_off_skips_the_model(fields, isolated, fake_model,
                                             monkeypatch, fake_systems):
    monkeypatch.setattr(app_module, "classify", lambda message: intent(**fields))
    model = fake_model()  # no canned replies: a model call would fail
    sid = verified_session(isolated)
    out = client.post("/chat", json={"session_id": sid, "message": "No hand-off please."}).json()
    assert HAND_OFF_REPLY in out["reply"]
    assert model.calls == []
    [case] = fake_systems.snow.cases
    assert "Reason:" in case["short_description"]  # the model-style summary names no reason: the template replaced it
    assert json.loads(case["u_conversation"]) == [{"role": "user", "content": "No hand-off please."}]


def test_covered_intent_still_goes_to_the_model(isolated, fake_model,
                                                monkeypatch, fake_systems):
    monkeypatch.setattr(app_module, "classify", lambda message: intent())
    model = fake_model(reply(text("It is on its way.")))
    sid = verified_session(isolated)
    out = client.post("/chat", json={"session_id": sid, "message": "Where is DS-20417?"}).json()
    assert "It is on its way." in out["reply"]
    assert len(model.calls) == 1
    assert fake_systems.snow.cases == []


SMASHED = "The screen was smashed when I got it. Order DS-20419."


def test_damage_flag_from_the_classifier_hands_off_without_the_model(isolated, fake_model, monkeypatch, fake_systems):
    """Damage on arrival in words the keyword rule misses (replay C25): the classifier's flag decides, in code."""
    monkeypatch.setattr(app_module, "classify",
                        lambda message: intent(intent="return_request", order_number="DS-20419", damaged=True))
    model = fake_model()  # no canned replies: a model call would fail
    sid = verified_session(isolated, "jack.wilson@example.com")
    out = client.post("/chat", json={"session_id": sid, "message": SMASHED}).json()
    assert HAND_OFF_REPLY in out["reply"]
    assert model.calls == []
    [case] = fake_systems.snow.cases
    assert "damage" in case["short_description"].lower()
    assert not fake_systems.drafts.rows
