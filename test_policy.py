"""Fast tests of the Confluence reader and the policy cut (Phase 5): canned pages, no network."""
from datetime import date

import pytest

import confluence
import policy
from confluence import ConfluenceError, FakeConfluence
from policy import PolicyError

BASE = "https://wiki.example"


def page(id="1001", title="Returns - UK", version=3, market="UK", valid_from=date(2026, 1, 1), valid_to=None,
         body="## Return window\nYou have 14 days.\n\n## Condition\nUnused items only.\n"):
    return {"id": id, "title": title, "version": version, "market": market, "valid_from": valid_from,
            "valid_to": valid_to, "link": f"{BASE}/wiki/spaces/POL/pages/{id}", "body": body}


def raw(id="1001", **meta):
    return {"id": id, "type": "page", "title": "Returns - UK", "version": {"number": 3, "when": "2026-09-01"},
            "metadata": {"market": "UK", "valid_from": "2026-01-01", "valid_to": None, **meta},
            "_links": {"webui": f"/wiki/spaces/POL/pages/{id}"}, "body": "## Return window\n14 days."}


def test_headings_cut_the_page():
    cuts = policy.sections(page())
    assert [c["heading"] for c in cuts] == ["Return window", "Condition"]
    assert cuts[0]["text"] == "You have 14 days."
    assert cuts[0]["page_id"] == "1001" and cuts[0]["version"] == 3


def test_market_dates_and_link_come_from_the_page():
    cut = policy.sections(page(id="1003", valid_to=date(2026, 11, 1)))[0]
    assert cut["market"] == "UK"
    assert cut["valid_from"] == date(2026, 1, 1) and cut["valid_to"] == date(2026, 11, 1)
    assert cut["link"] == f"{BASE}/wiki/spaces/POL/pages/1003"


def test_holiday_rule_with_dates_stays_in_one_section():
    body = "## Holiday returns\nBought 1 Nov - 24 Dec: return until 31 Jan.\n\n- Not for opened software.\n"
    cuts = policy.sections(page(body=body))
    assert len(cuts) == 1 and "31 Jan" in cuts[0]["text"] and "- Not for opened software." in cuts[0]["text"]


def test_two_versions_of_one_page_are_two_sets():
    old = page(id="1003", title="Delivery - UK", valid_to=date(2026, 11, 1), body="## Delivery times\n5 days.")
    new = page(id="1016", title="Delivery - UK (new rule)", valid_from=date(2026, 11, 2), body="## Delivery times\n3 days.")
    cuts = policy.all_sections([old, new])
    assert [(c["page_id"], c["valid_from"]) for c in cuts] == [("1003", date(2026, 1, 1)), ("1016", date(2026, 11, 2))]
    assert {c["heading"] for c in cuts} == {"Delivery times"}


def test_a_page_for_all_markets_keeps_its_market_value():
    assert policy.sections(page(market="ALL"))[0]["market"] == "ALL"


def test_text_before_the_first_heading_is_kept_under_the_title():
    cuts = policy.sections(page(body="Intro line.\n\n## Condition\nUnused."))
    assert cuts[0]["heading"] == "Returns - UK" and cuts[0]["text"] == "Intro line."


@pytest.mark.parametrize("field", ["market", "valid_from"])
def test_missing_metadata_raises_naming_the_page(field):
    with pytest.raises(PolicyError, match="1001"):
        policy.sections(page(**{field: None}))


def test_one_bad_page_fails_the_whole_cut():
    with pytest.raises(PolicyError, match="1002"):
        policy.all_sections([page(), page(id="1002", market=None)])


def test_the_cut_is_the_same_on_a_second_run():
    pages = [page(), page(id="1002", market="US")]
    assert policy.all_sections(pages) == policy.all_sections(pages)


def test_page_from_builds_link_and_dates():
    p = confluence.page_from(raw(valid_to="2026-11-01"), BASE)
    assert p["link"] == f"{BASE}/wiki/spaces/POL/pages/1001" and p["version"] == 3
    assert p["valid_from"] == date(2026, 1, 1) and p["valid_to"] == date(2026, 11, 1)


def test_page_from_leaves_missing_metadata_empty():
    p = confluence.page_from({"id": 5, "title": "T", "body": "x"}, BASE)
    assert p["market"] is None and p["valid_from"] is None and p["link"] is None and p["id"] == "5"


def test_pages_reads_the_list_with_one_get(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", BASE)
    paths = []

    def call(path):
        paths.append(path)
        return {"results": [raw(), raw(id="1002")], "size": 2}
    got = confluence.pages(call)
    assert [p["id"] for p in got] == ["1001", "1002"]
    assert paths == [confluence.LIST_PATH] and "spaceKey=POL" in paths[0]


def test_pages_without_a_list_is_an_error():
    with pytest.raises(ConfluenceError):
        confluence.pages(lambda path: {"oops": 1})


def test_fake_has_the_same_interface():
    fake = FakeConfluence([page(), page(id="1002")])
    assert [p["id"] for p in fake.pages()] == ["1001", "1002"]
    fake.fail = ConfluenceError("down")
    with pytest.raises(ConfluenceError):
        fake.pages()
