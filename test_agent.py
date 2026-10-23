"""Fast tests of the agent loop with a scripted fake model."""
import json

from agent import answer
from conftest import reply, text, tool_use

MAYA = "maya.ross@example.com"


def tool_result(model, call):
    """The tool result the loop sent back to the model on a given call."""
    return json.loads(model.calls[call]["messages"][-1]["content"][0]["content"])


def test_tool_use_then_final_text(fake_model):
    model = fake_model(
        reply(tool_use("find_order", {"number": "DS-20417"})),
        reply(text("Your order has shipped.")))
    assert answer("Where is DS-20417?", MAYA) == "Your order has shipped."
    assert len(model.calls) == 2
    assert tool_result(model, 1)["status"] == "shipped"


def test_usage_is_collected_per_call(fake_model):
    fake_model(reply(text("Hi.")))
    usage = []
    answer("Hello", MAYA, usage)
    assert len(usage) == 1


def test_unverified_chat_gets_no_order_data(fake_model):
    model = fake_model(
        reply(tool_use("find_order", {"number": "DS-20417"})),
        reply(text("Please enter your one-time code first.")))
    answer("Where is DS-20417?", None)
    assert "error" in tool_result(model, 1)
    assert list(tool_result(model, 1)) == ["error"]
