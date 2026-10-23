"""A scripted fake model: canned responses instead of calls to Claude."""
from types import SimpleNamespace

import pytest

import llm


def text(content):
    return SimpleNamespace(type="text", text=content)


def tool_use(name, args, id="toolu_1"):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=args)


def reply(*blocks):
    stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class FakeModel:
    """Returns the canned responses in order; keeps what it was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@pytest.fixture
def fake_model(monkeypatch):
    def install(*responses):
        model = FakeModel(responses)
        monkeypatch.setattr(llm.client, "messages",
                            SimpleNamespace(create=model.create))
        return model
    return install
