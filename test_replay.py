"""Fast test of the replay scoring: no calls to Claude."""
import pytest

from replay import score


@pytest.mark.parametrize("label", ["answer_policy", "answer_product",
                                   "start_return", "check_buyer_role"])
def test_later_intents_count_as_hand_off(label):
    assert score(label) == "hand_off"


@pytest.mark.parametrize("label", ["give_status", "ask_order_number",
                                   "hand_off"])
def test_other_labels_stay(label):
    assert score(label) == label
