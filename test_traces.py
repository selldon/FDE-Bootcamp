"""Every model call is recorded (B22, IT25)."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agent
import app as app_module
import llm
import refunds
import traces
from conftest import reply, text, tool_use
from masking import REMOVED

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
          "additionalProperties": False}


def test_one_trace_per_ask(fake_model, fake_traces):
    fake_model(reply(text("hello")))
    assert llm.ask("say hello") == "hello"
    [row] = fake_traces.rows
    assert (row["kind"], row["model"], row["prompt"], row["reply"]) == ("ask", llm.MODEL, "say hello", "hello")
    assert row["customer_hash"] is None and row["at"] is not None


def test_one_trace_per_chat_round_and_the_prompt_is_as_sent(fake_model, fake_traces):
    fake_model(reply(tool_use("find_order", {"number": "DS-20417"})), reply(text("done")))
    ctx = refunds.Context("maya.ross@example.com", "s1")
    agent.answer("where is DS-20417?", ctx)
    first, second = fake_traces.rows
    assert first["kind"] == second["kind"] == "chat"
    assert "where is DS-20417?" in first["prompt"] and "tool_result" not in first["prompt"]
    # the second round was sent the tool call and its result: that is what is stored
    assert "find_order" in second["prompt"] and "tool_result" in second["prompt"]
    assert "find_order" in first["reply"] and second["reply"].count("done") == 1


def test_refusal_is_still_recorded(fake_model, fake_traces):
    refusal = SimpleNamespace(content=[text("")], stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"),
                              usage=SimpleNamespace(input_tokens=5, output_tokens=0))
    fake_model(refusal)
    with pytest.raises(ValueError):
        llm.ask("x")
    [row] = fake_traces.rows
    assert row["reply"] == "refusal: cyber" and row["input_tokens"] == 5


def test_cost_comes_from_tokens(fake_model, fake_traces, monkeypatch):
    monkeypatch.setattr(llm, "PRICES", {llm.MODEL: (2.0, 10.0)})
    response = reply(text("x"))
    response.usage = SimpleNamespace(input_tokens=1000, output_tokens=500)
    fake_model(response)
    llm.ask("p")
    [row] = fake_traces.rows
    assert (row["input_tokens"], row["output_tokens"]) == (1000, 500)
    assert row["cost"] == pytest.approx(0.007)


def test_a_model_without_a_price_has_no_cost(fake_model, fake_traces):
    fake_model(reply(text("x")))
    llm.ask("p", model="some-other-model")
    assert fake_traces.rows[0]["cost"] is None


def test_failed_write_does_not_fail_the_reply_and_is_counted(fake_model, monkeypatch):
    monkeypatch.setattr(traces, "_sink", traces.FakeTraces(fail=True))
    fake_model(reply(text("hello")), reply(text("again")))
    assert llm.ask("a") == "hello"
    assert llm.ask("b") == "again"
    assert traces.failures == 2


def test_the_stored_prompt_and_reply_carry_no_card_number(fake_model, fake_traces):
    fake_model(reply(text("your card 4111 1111 1111 1111 is noted")))
    llm.ask("pay with 4111 1111 1111 1111")
    [row] = fake_traces.rows
    assert "4111" not in row["prompt"] + row["reply"] and REMOVED in row["prompt"] and REMOVED in row["reply"]


def test_chat_endpoint_gives_its_calls_the_session_id(fake_model, fake_traces):
    intent = json.dumps({"summary": "s", "intent": "other", "order_number": None,
                         "needs_human": False, "damaged": False, "language": "en"})
    fake_model(reply(text(intent)), reply(text("hi")))
    out = TestClient(app_module.app).post("/chat", json={"message": "hello"}).json()
    kinds_ = [(r["kind"], r["session_id"]) for r in fake_traces.rows]
    assert kinds_ == [("ask", out["session_id"]), ("chat", out["session_id"])]
    assert traces.current_session.get() is None  # reset after the turn


def test_session_is_not_shared_between_calls_outside_a_chat(fake_model, fake_traces):
    fake_model(reply(text("x")))
    llm.ask("p")
    assert fake_traces.rows[0]["session_id"] is None


def test_only_llm_calls_the_anthropic_client():
    for path in Path(".").glob("*.py"):
        if path.name == "llm.py" or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "anthropic":
                names = {a.name for a in node.names}
                assert not names & {"Anthropic", "AsyncAnthropic"}, path
            if isinstance(node, ast.Attribute) and node.attr == "messages" and \
                    isinstance(node.value, ast.Attribute) and node.value.attr == "client":
                pytest.fail(f"{path} reaches the model client")
            if isinstance(node, ast.Name) and node.id in ("Anthropic", "AsyncAnthropic"):
                pytest.fail(f"{path} builds a client")
