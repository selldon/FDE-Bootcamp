"""Fast test of the replay scoring: no calls to Claude."""
import pytest

from agent import NO_PAGE_REPLY, OFFER_REPLY, Result
from replay import GOAL, expected, gate, policy_key, policy_taken, score


@pytest.mark.parametrize("label", ["answer_product", "check_buyer_role"])
def test_later_intents_count_as_hand_off(label):
    assert score(label) == "hand_off"


@pytest.mark.parametrize("label", ["give_status", "ask_order_number",
                                   "hand_off", "start_return", "answer_policy"])
def test_other_labels_stay(label):
    assert score(label) == label

LINK_1001 = "http://127.0.0.1:8041/wiki/spaces/POL/pages/1001"


def reply(text, action="reply", policy=True):
    return Result(text, action, 1, policy)


def test_a_policy_reply_with_the_keys_page_is_right():
    assert policy_taken(reply(f"14 days. {LINK_1001}"), "1001") == "answer_policy"


def test_a_policy_reply_with_another_page_is_wrong():
    assert policy_taken(reply(f"14 days. {LINK_1001}"), "1013") == "wrong_page"
    assert policy_taken(reply(f"Not on our pages, but see {LINK_1001}"), None) == "wrong_page"


def test_no_page_means_a_person_is_offered_and_no_link():
    assert policy_taken(reply(NO_PAGE_REPLY), None) == "offer_person"
    assert policy_taken(reply(OFFER_REPLY), "1013") == "offer_person"  # offering a person where the key has a page is a miss
    assert policy_taken(reply("A person will help.", "hand_off", policy=False), None) == "offer_person"


def test_a_link_without_the_tool_is_not_counted():
    assert policy_taken(reply(f"See {LINK_1001}", policy=False), "1001") == "no_link"


def test_the_key_decides_what_a_policy_chat_should_end_in():
    key = policy_key()
    assert expected({"id": "C07", "action": "answer_policy"}, key) == "answer_policy"
    assert expected({"id": "C32", "action": "answer_policy"}, key) == "offer_person"
    assert expected({"id": "C01", "action": "give_status"}, key) == "give_status"


# Brief-ci "the eval gate": at least 36 of 40 right actions, nobody who needs a person left with the assistant, and a replay
# that writes nothing. Each run here is the shape play() returns.
def runs(right, wrong=0, stayed=0):
    ok = [{"id": f"C{i}", "taken": "give_status", "expected": "give_status", "needs_human": False} for i in range(right)]
    miss = [{"id": f"M{i}", "taken": "hand_off", "expected": "give_status", "needs_human": False} for i in range(wrong)]
    left = [{"id": f"S{i}", "taken": "reply", "expected": "hand_off", "needs_human": True} for i in range(stayed)]
    return ok + miss + left


def test_the_goal_is_36_of_40():
    assert GOAL == 36


def test_36_of_40_with_nobody_left_and_no_draft_passes():
    assert gate(runs(36, 4), drafts=0) == []


def test_35_of_40_fails_and_says_the_score():
    failures = gate(runs(35, 5), drafts=0)
    assert len(failures) == 1 and "35 of 40" in failures[0]


def test_a_chat_that_needed_a_person_and_stayed_fails_even_at_a_high_score():
    failures = gate(runs(39, 0, stayed=1), drafts=0)
    assert any("S0" in f for f in failures)


def test_a_draft_written_by_the_replay_fails():
    assert any("draft" in f for f in gate(runs(40), drafts=1))
