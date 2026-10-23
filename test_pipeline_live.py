"""Live check: the pipeline on the real Ledgerline copy and the real SFTP server. Run on request.

Writes to the real order store (upserts only), so it runs the pipeline twice and compares.
"""
import pytest

import pipeline
import store

pytestmark = pytest.mark.live


def _content(db):
    with db._connect() as conn:
        return (conn.execute("SELECT * FROM orders ORDER BY number").fetchall(),
                conn.execute("SELECT * FROM parcels ORDER BY tracking").fetchall())


def test_two_runs_leave_the_same_store():
    db = store.Store()
    first_counts = pipeline.run(db)
    first = _content(db)
    second_counts = pipeline.run(db)
    assert second_counts == first_counts
    assert _content(db) == first
    print(first_counts)
