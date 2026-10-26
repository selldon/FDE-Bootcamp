"""The answer key of G4 names the 8 policy conversations and nothing else (D2)."""
import json


def load(name):
    with open(f"data/{name}.json") as f:
        return json.load(f)


def test_the_key_covers_exactly_the_policy_conversations():
    policy = {c["id"] for c in load("conversations") if c["action"] == "answer_policy"}
    assert set(load("policy_key")["key"]) == policy
    assert len(policy) == 8


def test_every_entry_has_a_page_or_a_reason_for_none():
    for entry in load("policy_key")["key"].values():
        assert "page" in entry and entry["why"]
        assert entry["page"] is None or entry["page"].isdigit()
