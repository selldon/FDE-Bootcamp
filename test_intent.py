"""The hand-off gate shared by the chat service and the shadow worker."""
import pytest

from intent import COVERED, handoff_reason


def make(intent="order_status", needs_human=False, damaged=False):
    return {"intent": intent, "needs_human": needs_human, "damaged": damaged}


@pytest.mark.parametrize("intent, reason", [
    (make(needs_human=True), "needs_human"),
    (make(damaged=True), "damaged"),
    (make(intent="contract_price"), "not_covered"),
    (make(intent="product_question"), "not_covered"),
])
def test_each_reason(intent, reason):
    assert handoff_reason(intent) == reason


def test_order_when_several_apply():
    assert handoff_reason(make("contract_price", needs_human=True, damaged=True)) == "needs_human"
    assert handoff_reason(make("contract_price", damaged=True)) == "damaged"


@pytest.mark.parametrize("name", sorted(COVERED))
def test_covered_intent_passes(name):
    assert handoff_reason(make(name)) is None
