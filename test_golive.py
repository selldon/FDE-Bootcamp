"""Fast tests of the launch switch and the groups: no network, no database."""
from datetime import UTC, datetime, timedelta

import pytest
from psycopg import sql

import golive
from golive import ASSISTANT, CONTROL, PERSON, FakeGoLiveStore, group_of

IDS = [f"visitor-{i}" for i in range(10_000)]
T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


def live_store(**changes):
    store = FakeGoLiveStore()
    store.create_tables()
    store.set_settings(**{"on": True, **changes})
    return store


def chat(chat_id, minutes=0, **extra):
    return {"visitor_id": "v1", "chat_id": chat_id, "group_name": ASSISTANT, "intent": "order_status",
            "outcome": "resolved", "created_at": T0 + timedelta(minutes=minutes), **extra}


def test_the_same_id_gives_the_same_group_every_time():
    assert {group_of("visitor-42", 0.05) for _ in range(20)} in ({ASSISTANT}, {CONTROL})
    assert [group_of(i, 0.25) for i in IDS[:500]] == [group_of(i, 0.25) for i in IDS[:500]]


def test_about_five_percent_of_ten_thousand_ids_are_the_assistant_group():
    n = sum(group_of(i, 0.05) == ASSISTANT for i in IDS)
    assert 400 <= n <= 600  # 500 expected; a binomial spread is about 22


def test_share_zero_and_one_are_nobody_and_everybody():
    assert not any(group_of(i, 0) == ASSISTANT for i in IDS[:1000])
    assert all(group_of(i, 1) == ASSISTANT for i in IDS[:1000])


def test_widening_to_25_percent_only_adds_visitors():
    five = {i for i in IDS if group_of(i, 0.05) == ASSISTANT}
    quarter = {i for i in IDS if group_of(i, 0.25) == ASSISTANT}
    assert five < quarter
    assert 2300 <= len(quarter) <= 2700


def test_a_different_key_gives_a_different_split():
    assert any(group_of(i, 0.5) != group_of(i, 0.5, key=b"another") for i in IDS[:200])


def test_a_fresh_store_is_off_so_everything_goes_to_a_person():
    store = FakeGoLiveStore()
    store.create_tables()
    assert store.settings()["on"] is False
    assert {golive.route(store, i, "order_status") for i in IDS[:200]} == {PERSON}


def test_off_sends_everyone_to_a_person_even_with_a_full_share():
    store = live_store(share=1.0, on=False)
    assert {golive.route(store, i, "order_status") for i in IDS[:200]} == {PERSON}


def test_an_intent_that_is_not_live_goes_to_a_person():
    store = live_store(share=1.0)
    assert golive.route(store, "v1", "return_request") == PERSON
    assert golive.route(store, "v1", "order_status") == ASSISTANT


def test_a_live_intent_routes_by_the_visitors_group():
    store = live_store(share=0.05)
    for i in IDS[:300]:
        assert golive.route(store, i, "order_status") == group_of(i, 0.05)


def test_the_settings_are_read_at_every_request_so_no_deploy_is_needed():
    store = live_store(share=1.0)
    assert golive.route(store, "v1", "order_status") == ASSISTANT
    store.set_settings(on=False)
    assert golive.route(store, "v1", "order_status") == PERSON  # the very next request
    store.set_settings(on=True, intents=[])
    assert golive.route(store, "v1", "order_status") == PERSON
    store.set_settings(intents=["order_status"], share=0)
    assert golive.route(store, "v1", "order_status") == CONTROL


def test_set_settings_keeps_what_is_left_out_and_moves_changed_at():
    store = FakeGoLiveStore()
    store.create_tables()
    after = store.set_settings(share=0.25, now=T0)
    assert after == {"share": 0.25, "intents": ["order_status"], "on": False, "changed_at": T0}


@pytest.mark.parametrize("share", [-0.1, 1.1, True, "0.05", None])
def test_a_bad_share_is_rejected_and_nothing_changes(share):
    store = live_store()
    before = store.settings()
    with pytest.raises(ValueError):
        store.set_settings(share=share) if share is not None else golive.check_settings(share, [], True)
    assert store.settings() == before


def test_bad_intents_are_rejected():
    with pytest.raises(ValueError):
        golive.check_settings(0.05, "order_status", True)
    with pytest.raises(ValueError):
        golive.check_settings(0.05, [""], True)


def test_settings_before_create_tables_is_an_error():
    with pytest.raises(RuntimeError):
        FakeGoLiveStore().settings()


def test_a_chat_is_saved_once_and_keeps_the_simulated_flag_and_day():
    store = FakeGoLiveStore()
    assert store.save_chat(chat("C1", simulated=True, sim_day=3)) is True
    assert store.save_chat(chat("C1", outcome="something else")) is False
    row = store.chats()[0]
    assert row["outcome"] == "resolved" and row["simulated"] is True and row["sim_day"] == 3


def test_a_chat_that_is_not_marked_simulated_is_stored_as_not_simulated():
    store = FakeGoLiveStore()
    store.save_chat(chat("C1"))
    assert store.chats()[0]["simulated"] is False and store.chats()[0]["handed_off"] is False


def test_chats_can_be_filtered_by_simulated_and_come_oldest_first():
    store = FakeGoLiveStore()
    store.save_chat(chat("C2", minutes=5, simulated=True, sim_day=1))
    store.save_chat(chat("C1", minutes=1))
    assert [r["chat_id"] for r in store.chats()] == ["C1", "C2"]
    assert [r["chat_id"] for r in store.chats(simulated=True)] == ["C2"]
    assert [r["chat_id"] for r in store.chats(simulated=False)] == ["C1"]


def test_a_chat_needs_a_known_group():
    with pytest.raises(ValueError):
        FakeGoLiveStore().save_chat(chat("C1", group_name="everyone"))


def test_the_tables_are_new_and_additive():
    statements = [s.as_string() for s in golive.tables("t_settings", "t_chats")]
    assert all(s.startswith("CREATE TABLE IF NOT EXISTS") for s in statements)
    assert not any(word in s.upper() for s in statements for word in ("DROP", "ALTER", "DELETE", "TRUNCATE"))
    assert "simulated" in statements[1] and "sim_day" in statements[1]


def test_the_real_store_names_its_tables_by_parameter():
    store = golive.GoLiveStore(url="postgresql://unused", settings_table="s_x", chats_table="c_x")
    assert store.chats_table == sql.Identifier("c_x") and store.settings_name == "s_x"


def test_a_chat_row_can_be_updated_in_its_outcome_columns_only():
    store = FakeGoLiveStore()
    store.save_chat(chat("C1"))
    assert store.update_chat("C1", outcome="handed_off", handed_off=1, group_name="person") is True
    row = store.chats()[0]
    assert (row["outcome"], row["handed_off"], row["group_name"]) == ("handed_off", True, "person")
    assert store.update_chat("nope", outcome="x") is False
    for bad in ({"simulated": True}, {"sim_day": 2}, {"visitor_id": "x"}, {"group_name": "everyone"}):
        with pytest.raises(ValueError):
            store.update_chat("C1", **bad)
