"""Fast tests of docs/week-2-report.md: it is rendered from the page's numbers (GET /api/golive), never typed by hand."""
import copy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app as chat_app
import golive_report as report
import pilot
from golive import ASSISTANT, CONTROL, FakeGoLiveStore

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
_ids = iter(range(10**6))


def chat(group, outcome, day, **extra):
    n = next(_ids)
    return {"visitor_id": f"v{n}", "chat_id": f"C{n}", "group_name": group, "intent": "order_status", "outcome": outcome,
            "simulated": True, "sim_day": day, "created_at": T0 + timedelta(days=day), "rating": 4,
            "confidently_wrong": False, "needs_person": False, **extra}


def day_rows(day, wrong=0, assistant=4):
    rows = [chat(ASSISTANT, "give_status", day, confidently_wrong=i < wrong) for i in range(assistant)]
    rows.append(chat(ASSISTANT, "handed_off", day, handed_off=True, needs_person=True))
    rows += [chat(CONTROL, "resolved", day, handed_off=True) for _ in range(10)]
    return rows


def api_for(monkeypatch, rows):
    store = FakeGoLiveStore()
    store.create_tables()
    for row in rows:
        store.save_chat(row)
    monkeypatch.setattr(chat_app, "golive_store", lambda: store)
    return TestClient(chat_app.app).get("/api/golive").json()


@pytest.fixture
def breach(monkeypatch):
    """14 real days, one confidently wrong answer on day 8, then a drill day with 3 wrong and a clean clearing day."""
    rows = [r for d in range(1, 15) for r in day_rows(d, wrong=1 if d == 8 else 0)]
    rows += day_rows(15, wrong=3) + day_rows(16)
    return api_for(monkeypatch, rows)


@pytest.fixture
def clean(monkeypatch):
    return api_for(monkeypatch, [r for d in range(1, 15) for r in day_rows(d)])


@pytest.fixture
def short(monkeypatch):
    return api_for(monkeypatch, [r for d in range(1, 6) for r in day_rows(d)])


def body(text):
    return [line for line in text.splitlines() if line.strip()]


def test_the_first_lines_say_simulated_which_line_does_not_hold_and_the_recommendation(breach):
    lines = body(report.render(breach))
    assert lines[0].startswith("# Week 2 report")
    assert lines[1].startswith("**Simulated.**") and "simulated" in lines[1].lower()
    wrong = breach["lines"]["window"]["confidently_wrong"]
    assert wrong["status"] == "does not hold"
    assert lines[2].startswith("**One line does not hold") and "confidently wrong" in lines[2]
    assert wrong["detail"] in lines[2]  # "1 of 70 assistant chats", taken from the page
    assert lines[3].startswith("**Recommendation: do not widen") and "5 %" in lines[3] and "returns stay off" in lines[3]


def test_the_report_names_the_lines_from_the_data_and_pluralises(breach):
    other = copy.deepcopy(breach)
    other["lines"]["window"]["hand_off"]["status"] = "does not hold"
    other["lines"]["two_weeks"]["status"] = "does not hold"
    lines = body(report.render(other))
    assert lines[2].startswith("**Two lines do not hold") and "confidently wrong" in lines[2] and "hand-off" in lines[2]


def test_when_all_four_lines_hold_for_the_two_weeks_the_recommendation_is_25_percent_with_drafts_only(clean):
    assert clean["lines"]["two_weeks"]["status"] == "holds"
    lines = body(report.render(clean))
    assert lines[1].startswith("**Simulated.**")
    assert lines[2].startswith("**All four lines hold") and "does not hold" not in lines[2]
    assert "widen to 25 %" in lines[3] and "return_request" in lines[3] and "drafts only" in lines[3]


def test_with_fewer_than_14_days_nothing_is_widened_and_the_report_says_why(short):
    lines = body(report.render(short))
    assert lines[1].startswith("**Simulated.**")
    assert "not enough" in lines[2].lower() and "5 of 14" in lines[2]
    assert lines[3].startswith("**Recommendation: do not widen")


def test_the_table_has_every_line_with_its_limit_observed_value_n_interval_and_status(breach):
    text = report.render(breach)
    window = breach["lines"]["window"]
    for key in ("confidently_wrong", "hand_off", "unanswered", "rating"):
        assert window[key]["name"] in text
    assert "does not hold" in text and "holds" in text
    row = next(line for line in text.splitlines() if line.startswith("| confidently wrong"))
    assert "at most 1 %" in row and window["confidently_wrong"]["detail"].split(" assistant")[0].split(" of ")[1] in row


def test_operator_hours_are_resolved_chats_per_week_times_the_minutes_per_contact_scaled_by_the_share(breach):
    resolved = breach["window"]["assistant"]["resolved"]
    weeks = breach["days_with_chats"] / 7
    per_week = resolved / weeks
    hours_now = per_week * pilot.PERSON_MINUTES / 60
    text = report.render(breach)
    assert f"{hours_now:.1f} hours" in text  # at 5 %
    assert f"{hours_now / 0.05:.1f} hours" in text  # at 100 %
    assert f"{hours_now / 0.05 * 0.25:.1f} hours" in text  # at 25 %, the step not taken
    assert f"{pilot.PERSON_MINUTES} minutes" in text


def test_what_100_percent_would_mean_in_chats_and_wrong_answers_with_the_upper_end_said(breach):
    window = breach["window"]["assistant"]
    wrong = breach["lines"]["window"]["confidently_wrong"]
    weeks = breach["days_with_chats"] / 7
    chats_100 = window["decided"] / weeks / 0.05
    text = report.render(breach)
    assert f"{chats_100:,.0f} assistant chats a week" in text
    assert f"{chats_100 * wrong['value']:.0f}" in text  # wrong answers a week at the observed rate
    assert f"{chats_100 * wrong['interval'][1]:.0f}" in text  # and at the upper end of the interval
    assert "cannot show" in text.lower()


def test_drill_days_are_reported_apart_from_the_lines(breach):
    text = report.render(breach)
    assert breach["drill_days"] == [15, 16]
    section = text.split("## The drill", 1)[1].split("\n## ", 1)[0]
    assert "day 15" in section and "3 of 5" in section and "day 16" in section and "0 of 5" in section
    assert "not in the lines" in section.lower()


def test_no_drill_section_when_there_was_no_drill(clean):
    assert "## The drill" not in report.render(clean)


def test_the_assumptions_are_said_out_loud(breach):
    text = report.render(breach)
    section = text.split("## Assumptions", 1)[1].split("\n## ", 1)[0].lower()
    for word in ("simulated", "seeded", "linear", "interval", "other questions", "03:00"):
        assert word in section
    assert breach["repeat_note"] in text  # repeat contact: not measured, with its reason
    assert f"{breach['window']['person']} " in section.replace("\n", " ")  # chats that went straight to a person


def test_the_report_says_where_the_numbers_come_from_and_is_the_same_twice(breach):
    text = report.render(breach)
    assert "GET /api/golive" in text and "python golive_report.py" in text and breach["as_of"] in text
    assert report.render(breach) == text


def test_main_fetches_the_page_numbers_and_writes_the_file(breach, tmp_path, capsys):
    out = tmp_path / "week-2-report.md"
    assert report.main(["--out", str(out)], fetch=lambda url: breach) == 0
    assert out.read_text() == report.render(breach)
    assert str(out) in capsys.readouterr().out
