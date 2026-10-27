"""Fast tests of the go-live numbers and the rollback lines: no network, no database, no model."""
import json
from datetime import UTC, datetime, timedelta

import pytest

import golive
from golive import ASSISTANT, CONTROL, PERSON, FakeGoLiveStore

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
_ids = iter(range(10**6))


def chat(group, outcome="resolved", day=1, **extra):
    n = next(_ids)
    return {"visitor_id": f"v{n}", "chat_id": f"C{n}", "group_name": group, "intent": "order_status", "outcome": outcome,
            "simulated": True, "sim_day": day, "created_at": T0 + timedelta(days=day), "rating": 4, **extra}


def store_with(*rows):
    store = FakeGoLiveStore()
    for row in rows:
        store.save_chat(row)
    return store


def read(rows):
    data = golive.numbers(store_with(*rows), NOW)
    return data, golive.lines(data)


def filler(group, n, **extra):
    return [chat(group, **extra) for _ in range(n)]


# ---- the margins are pinned --------------------------------------------------------------------------------------

def test_the_signed_margins_are_pinned():
    assert golive.margins() == {"confidently_wrong": 0.01, "hand_off_min": 0.95, "unanswered_points": 0.03, "rating": 0.2}


# ---- each line at, just below and just above its limit -----------------------------------------------------------

@pytest.mark.parametrize(("wrong", "status"), [(0, "holds"), (1, "holds"), (2, "does not hold")])
def test_confidently_wrong_line_around_one_in_a_hundred(wrong, status):
    rows = filler(ASSISTANT, 100 - wrong) + filler(ASSISTANT, wrong, confidently_wrong=True) + filler(CONTROL, 10)
    _, result = read(rows)
    line = result["week"]["confidently_wrong"]
    assert line["status"] == status and line["n"] == 100 and line["limit"] == 0.01
    assert line["interval"][0] <= line["value"] <= line["interval"][1]


def test_the_day_alert_fires_on_one_wrong_answer_in_ten_chats():
    rows = (filler(ASSISTANT, 9, day=3) + [chat(ASSISTANT, day=3, confidently_wrong=True)] + filler(ASSISTANT, 150, day=2)
            + filler(CONTROL, 20))
    _, result = read(rows)
    assert result["day"]["alert"] is True and result["day"]["confidently_wrong"]["n"] == 10
    assert result["week"]["confidently_wrong"]["status"] == "holds"  # 1 in 160 over the week
    assert result["alert_days"] == [3]


@pytest.mark.parametrize(("handed", "status"), [(94, "does not hold"), (95, "holds"), (96, "holds")])
def test_hand_off_line_around_95_in_100(handed, status):
    rows = (filler(ASSISTANT, handed, outcome="handed_off", needs_person=True)
            + filler(ASSISTANT, 100 - handed, outcome="reply", needs_person=True) + filler(CONTROL, 10))
    _, result = read(rows)
    line = result["week"]["hand_off"]
    assert line["status"] == status and line["n"] == 100


def unanswered_rows(assistant_unanswered, control_unanswered=10):
    return (filler(ASSISTANT, 100 - assistant_unanswered) + filler(ASSISTANT, assistant_unanswered, outcome="unanswered")
            + filler(CONTROL, 100 - control_unanswered) + filler(CONTROL, control_unanswered, outcome="unanswered"))


@pytest.mark.parametrize(("unanswered", "status"), [(12, "holds"), (13, "holds"), (14, "does not hold")])
def test_unanswered_line_around_three_points_worse_than_control(unanswered, status):
    _, result = read(unanswered_rows(unanswered))
    line = result["week"]["unanswered"]
    assert line["status"] == status and line["n"] == (100, 100)
    assert line["interval"][0] < line["value"] < line["interval"][1]


@pytest.mark.parametrize(("fours", "status"), [(81, "holds"), (80, "holds"), (79, "does not hold")])
def test_rating_line_around_a_fifth_of_a_point_lower(fours, status):
    rows = (filler(ASSISTANT, fours, rating=4) + filler(ASSISTANT, 100 - fours, rating=3) + filler(CONTROL, 100, rating=4))
    _, result = read(rows)
    line = result["week"]["rating"]
    assert line["status"] == status and line["n"] == (100, 100)


def test_a_better_assistant_never_breaches_the_unanswered_or_rating_line():
    rows = filler(ASSISTANT, 50, rating=5) + filler(CONTROL, 50, outcome="unanswered", rating=2) + filler(CONTROL, 50, rating=2)
    _, result = read(rows)
    assert result["week"]["unanswered"]["status"] == result["week"]["rating"]["status"] == "holds"


# ---- groups with no chats ----------------------------------------------------------------------------------------

def test_no_chats_at_all_is_not_enough_never_an_error():
    data, result = read([])
    assert data["total"] == 0 and data["last_day"] is None
    for window in ("week", "window"):
        assert {x["status"] for x in result[window].values()} == {"not enough yet"}
    assert result["day"]["confidently_wrong"]["status"] == "not enough yet" and result["day"]["alert"] is False
    assert result["two_weeks"]["status"] == "not enough yet"


def test_a_group_with_no_chats_gives_not_enough_yet():
    for rows in (filler(ASSISTANT, 20), filler(CONTROL, 20)):
        data, result = read(rows)
        assert result["week"]["unanswered"]["status"] == result["week"]["rating"]["status"] == "not enough yet"
        assert data["week"]["difference"]["unanswered"] is None


def test_control_chats_still_waiting_for_an_outcome_are_not_counted_as_answered_or_not():
    data, _ = read(filler(CONTROL, 5, outcome="queued") + filler(CONTROL, 5))
    control = data["week"][CONTROL]
    assert (control["chats"], control["decided"], control["resolved"]) == (10, 5, 5)


def test_person_chats_are_counted_but_not_compared():
    data, _ = read(filler(PERSON, 7) + filler(ASSISTANT, 3) + filler(CONTROL, 3))
    assert data["week"]["person"] == 7 and data["week"]["total"] == 13
    assert data["week"][ASSISTANT]["chats"] == 3


# ---- the figures per group ---------------------------------------------------------------------------------------

def test_the_figures_of_a_group_and_cost_per_contact():
    rows = [chat(ASSISTANT, "give_status", cost=0.02, rating=5, repeat_contact=False),
            chat(ASSISTANT, "handed_off", cost=0.03, rating=3, repeat_contact=True),
            chat(ASSISTANT, "reply", cost=0.01, rating=1, repeat_contact=True),
            chat(CONTROL, "resolved", rating=4, repeat_contact=False), chat(CONTROL, "unanswered", rating=2)]
    data, _ = read(rows)
    a, c = data["window"][ASSISTANT], data["window"][CONTROL]
    assert (a["resolved"], a["handed_off"], a["unanswered"], a["repeat_contacts"], a["rating"]) == (1, 1, 1, 2, 3)
    assert a["cost_per_contact"] == pytest.approx((0.06 + 7.0) / 3)  # model calls plus one person contact
    assert c["cost_per_contact"] == pytest.approx(7.0)             # every control chat is a person
    assert (c["repeat_contacts"], c["repeat_known"]) == (0, 1)


def test_resolved_handed_off_and_unanswered_add_up_to_the_decided_chats():
    data, _ = read(unanswered_rows(13) + filler(ASSISTANT, 4, outcome="handed_off"))
    for g in (ASSISTANT, CONTROL):
        x = data["window"][g]
        assert x["resolved"] + x["handed_off"] + x["unanswered"] == x["decided"] == x["chats"]


def test_the_difference_interval_contains_the_difference_and_shrinks_with_more_chats():
    small = golive.diff_interval(13, 100, 10, 100)
    big = golive.diff_interval(130, 1000, 100, 1000)
    assert small[0] == pytest.approx(0.03) == pytest.approx(big[0])
    assert small[1] < small[0] < small[2] and big[1] < big[0] < big[2]
    assert big[2] - big[1] < small[2] - small[1]


def test_the_mean_difference_needs_two_ratings_each():
    assert golive.mean_diff_interval([4], [4, 5]) is None
    d, low, high = golive.mean_diff_interval([4, 5, 3, 4], [5, 5, 4, 5])
    assert low < d < high and d == pytest.approx(-0.75)


# ---- windows and the two-week check ------------------------------------------------------------------------------

def test_day_week_and_window_are_the_last_1_7_and_14_days():
    rows = [chat(ASSISTANT, day=d) for d in range(1, 15)]
    data, _ = read(rows)
    assert (data["day"]["total"], data["week"]["total"], data["window"]["total"]) == (1, 7, 14)
    assert data["last_day"] == 14 and sorted(data["by_day"]) == list(range(1, 15))


def fourteen_days(**assistant_extra):
    rows = []
    for d in range(1, 15):
        rows += [chat(ASSISTANT, day=d, needs_person=False, **assistant_extra) for _ in range(5)]
        rows += [chat(ASSISTANT, "handed_off", day=d, needs_person=True)]
        rows += [chat(CONTROL, day=d) for _ in range(20)]
    return rows


def test_two_weeks_hold_when_all_four_lines_hold():
    _, result = read(fourteen_days())
    assert result["two_weeks"] == {"status": "holds", "days": 14, "needed": 14}


def test_two_weeks_are_not_decided_before_14_days_of_chats():
    _, result = read([c for c in fourteen_days() if c["sim_day"] <= 13])
    assert result["two_weeks"]["status"] == "not enough yet"


def test_one_failing_line_stops_the_two_weeks():
    rows = fourteen_days() + [chat(ASSISTANT, day=14, confidently_wrong=True) for _ in range(3)]
    _, result = read(rows)
    assert result["window"]["confidently_wrong"]["status"] == "does not hold"
    assert result["two_weeks"]["status"] == "does not hold"


def test_numbers_are_plain_data_and_the_same_store_gives_the_same_numbers():
    store = store_with(*fourteen_days())
    first = golive.numbers(store, NOW)
    assert first == golive.numbers(store, NOW) and first["as_of"] == NOW
    json.dumps(golive.lines(first))


def test_the_margins_come_from_the_assumptions_file(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"margins": {"rating": 0.5}}))
    assert golive.margins(path) == {"rating": 0.5}


# ---- repeat contact: not measured (the old chats are 15 customers, so no baseline can be taken from them) -----------

def test_repeat_contact_is_not_compared_even_when_both_groups_carry_the_values():
    rows = [chat(ASSISTANT, "give_status", repeat_contact=True), chat(ASSISTANT, "give_status", repeat_contact=False),
            chat(CONTROL, "resolved", repeat_contact=True), chat(CONTROL, "resolved", repeat_contact=True)]
    data, _ = read(rows)
    assert data["window"]["difference"]["repeat"] is None  # no number, no interval: nothing was measured
    assert data["window"][CONTROL]["repeat_known"] == 2  # the stored values are not touched, only not compared


def test_the_numbers_say_why_repeat_contact_is_not_measured_in_one_line():
    data, _ = read([chat(ASSISTANT), chat(CONTROL)])
    note = data["repeat_note"]
    assert note == golive.REPEAT_NOT_MEASURED
    assert "15 customers" in note and "\n" not in note and note.startswith("Not measured")


# ---- control chats as the service writes them: queued means handed_off is true, whatever happened after ----------------

@pytest.mark.parametrize(("group", "outcome", "handed_off", "expected"), [
    (CONTROL, "unanswered", True, "unanswered"),   # reached the queue, then the customer left without an answer
    (CONTROL, "resolved", True, "resolved"),
    (CONTROL, "handed_off", True, "handed_off"),
    (CONTROL, "queued", True, "handed_off"),       # not labelled yet: in the queue
    (ASSISTANT, "handed_off", True, "handed_off"),
    (ASSISTANT, "give_status", False, "resolved"),
    (ASSISTANT, "reply", False, "unanswered"),     # an assistant chat that ended any other way
    (ASSISTANT, "unanswered", True, "unanswered"),
])
def test_classify_reads_the_outcome_before_the_handed_off_flag(group, outcome, handed_off, expected):
    assert golive.classify({"group_name": group, "outcome": outcome, "handed_off": handed_off}) == expected


def test_control_unanswered_chats_are_counted_though_every_queued_chat_is_marked_handed_off():
    rows = (filler(CONTROL, 6, outcome="resolved", handed_off=True)
            + filler(CONTROL, 3, outcome="unanswered", handed_off=True)
            + filler(CONTROL, 1, outcome="handed_off", handed_off=True))
    data, _ = read(rows)
    c = data["window"][CONTROL]
    assert (c["resolved"], c["unanswered"], c["handed_off"], c["decided"]) == (6, 3, 1, 10)


def test_the_unanswered_line_sees_the_controls_unanswered_chats_with_the_service_s_rows():
    rows = (filler(ASSISTANT, 20, outcome="give_status")
            + filler(CONTROL, 18, outcome="resolved", handed_off=True)
            + filler(CONTROL, 2, outcome="unanswered", handed_off=True))
    data, result = read(rows)
    difference = data["window"]["difference"]["unanswered"][0]
    assert difference == pytest.approx(-0.1)  # the assistant left nobody without an answer, control left 10 %
    assert result["window"]["unanswered"]["status"] == "holds"
