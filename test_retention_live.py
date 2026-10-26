"""Live check: traces, purge and erasure on the real PostgreSQL. Run on request.

Own tables (`traces_check`, `erasures_check`) created as TEMPORARY tables (search_path = pg_temp):
the real `traces` and `erasures` are never touched and nothing is left behind.
"""
from datetime import UTC, datetime, timedelta

import pytest

import retention
import traces
from test_store_live import _Shared

pytestmark = pytest.mark.live

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def row(days_old, session_id, customer=None):
    return {"at": NOW - timedelta(days=days_old), "session_id": session_id, "customer_hash": customer,
            "model": "m", "prompt": "p", "reply": "r", "input_tokens": 1, "output_tokens": 1,
            "cost": None, "kind": "ask"}


def test_write_purge_erase_and_read_back(monkeypatch):
    monkeypatch.setenv("TRACE_HMAC_KEY", "live-check-key")
    t = traces.Traces(traces="traces_check", erasures="erasures_check", options="-c search_path=pg_temp")
    conn = t._connect()
    t._connect = lambda: _Shared(conn)  # type: ignore[method-assign]
    t.create_tables()

    def count():
        return conn.execute("SELECT count(*) FROM traces_check").fetchone()[0]

    mine = traces.customer_hash("live.check@example.com")
    for r in (row(89, "a"), row(91, "b"), row(5, "s1"), row(5, "s2", mine), row(5, "s3", "someone-else")):
        t.add(r)
    assert count() == 5
    assert retention.purge(now=NOW, sink=t) == 1 and count() == 4
    t.fill_hash("s1", mine)
    assert t.delete_customer(mine, ["s1"]) == 2 and count() == 2  # s1 and s2; a and s3 stay
    t.log_erasure(NOW, 2)
    assert conn.execute("SELECT rows_deleted FROM erasures_check").fetchall() == [(2,)]
    conn.close()
