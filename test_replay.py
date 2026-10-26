"""Fast test of the replay scoring: no calls to Claude."""
import pytest

from agent import NO_PAGE_REPLY, OFFER_REPLY, Result
from replay import expected, policy_key, policy_taken, score


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
