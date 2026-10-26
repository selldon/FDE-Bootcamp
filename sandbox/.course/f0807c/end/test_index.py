"""Our copy of the policies must be as new as Confluence."""
from index_policies import stale_pages


def test_no_page_changed_after_the_index():
    assert stale_pages() == []
