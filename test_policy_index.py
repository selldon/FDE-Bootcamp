"""Fast tests of the policy index (Phase 6): FakeConfluence, FakeEmbedder, FakeIndex - no network, no database."""
from datetime import date

import pytest

import policy_index
from confluence import ConfluenceError, FakeConfluence
from embedder import FakeEmbedder
from policy import PolicyError
from policy_index import FakeIndex, rebuild
from test_policy import page


def build(pages, index=None, embedder=None):
    index = index if index is not None else FakeIndex()
    n = rebuild(FakeConfluence(pages), embedder or FakeEmbedder(), index)
    return n, index


def test_rebuild_twice_gives_the_same_index():
    pages = [page(), page(id="1002", title="Returns - US", market="US")]
    n1, index = build(pages)
    first = index.all()
    n2, _ = build(pages, index)
    assert n1 == n2 == 4
    assert index.all() == first
    assert index.counts_by_market() == {"UK": 2, "US": 2}


def test_a_changed_page_replaces_its_sections():
    _, index = build([page(version=3), page(id="1002", market="US")])
    _, index = build([page(version=3, body="## Return window\nYou have 21 days.\n"), page(id="1002", market="US")], index)
    uk = [r for r in index.all() if r["page_id"] == "1001"]
    assert [(r["heading"], r["text"]) for r in uk] == [("Return window", "You have 21 days.")]
    assert len([r for r in index.all() if r["page_id"] == "1002"]) == 2


def test_a_removed_page_leaves_no_sections():
    _, index = build([page(), page(id="1002", market="US")])
    build([page()], index)
    assert {r["page_id"] for r in index.all()} == {"1001"}


def test_a_failure_in_the_middle_leaves_the_old_index():
    _, index = build([page()])
    old = index.all()
    index.fail_after = 1
    with pytest.raises(RuntimeError):
        build([page(id="1002", market="US"), page(id="1003", market="DE")], index)
    assert index.all() == old
    index.fail_after = None
    for broken in (ConfluenceError("down"), PolicyError("page 9 has no market")):
        source = FakeConfluence([page(id="1002", market="US")])
        source.fail = broken
        with pytest.raises(type(broken)):
            rebuild(source, FakeEmbedder(), index)
        assert index.all() == old
    embedder = FakeEmbedder()
    embedder.fail = RuntimeError("model missing")
    with pytest.raises(RuntimeError):
        build([page(id="1002", market="US")], index, embedder)
    assert index.all() == old
    with pytest.raises(PolicyError):
        build([page(id="1002", market=None)], index)
    assert index.all() == old


def test_a_later_version_is_stored_next_to_the_old_one():
    old = page(version=3, valid_to=date(2026, 12, 31))
    new = page(version=4, valid_from=date(2027, 1, 1), body="## Return window\nYou have 21 days.\n")
    _, index = build([old, new])
    rows = [r for r in index.all() if r["heading"] == "Return window"]
    assert [(r["version"], r["valid_from"], r["valid_to"]) for r in rows] == [
        (3, date(2026, 1, 1), date(2026, 12, 31)), (4, date(2027, 1, 1), None)]


def test_two_pages_with_one_heading_are_two_sections():
    """Two rules for one thing are two pages (1003, 1016): the key includes the page id."""
    _, index = build([page(id="1003"), page(id="1016")])
    assert len([r for r in index.all() if r["heading"] == "Return window"]) == 2


def test_the_same_heading_twice_on_one_page_is_an_error():
    with pytest.raises(PolicyError, match="twice"):
        build([page(body="## Rule\nA\n\n## Rule\nB\n")])


def test_each_section_is_embedded_with_its_heading_and_text():
    embedder = FakeEmbedder()
    build([page()], embedder=embedder)
    assert embedder.calls == [["Return window\nYou have 14 days.", "Condition\nUnused items only."]]


def test_the_fake_embedder_is_deterministic_and_puts_shared_words_close():
    e = FakeEmbedder()
    a, b, c = e.embed(["refund within 14 days", "refund within 14 days", "carrier pickup point"])
    assert a == b
    dot = lambda x, y: sum(p * q for p, q in zip(x, y, strict=True))
    assert dot(a, e.embed(["refund 14 days"])[0]) > dot(a, c)


def test_the_real_embedder_is_not_loaded_on_import():
    import embedder
    assert embedder._model is None


def test_sql_names_the_key_and_the_vector_extension():
    text = " ".join(s.as_string() for s in policy_index.tables())
    assert "CREATE EXTENSION IF NOT EXISTS vector" in text
    assert "PRIMARY KEY (page_id, version, heading)" in text and "tsvector" in text
