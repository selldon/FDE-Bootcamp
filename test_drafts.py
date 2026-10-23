"""Fast tests of the return draft (Phase 5): the fake holding table, the one INSERT, the retry."""
import ast
import re
from decimal import Decimal
from pathlib import Path

import oracledb
import pytest

import drafts

SOURCE = Path(drafts.__file__).read_text()
ORDER = {"number": "DS-1", "lines": [
    {"line": 1, "unit_price": Decimal("100.00"), "quantity": 1, "tax": Decimal("20.00")},
    {"line": 2, "unit_price": Decimal("40.00"), "quantity": 2, "tax": Decimal("16.01")}]}


class Cursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def execute(self, sql, binds=None):
        self.conn.log.append((sql, binds))
        if sql == drafts.INSERT:
            if self.conn.fail:
                raise self.conn.fail
            self.conn.insert_row(binds["order_no"], binds["line_no"], binds["amount"],
                                 binds["req_key"], binds["status"])
        elif sql == drafts.BY_KEY:
            row = self.conn.table.rows.get(binds["req_key"])
            self.rows = [row] if row else []

    def fetchall(self):
        return self.rows


class Connection(drafts.FakeDrafts):
    """A connection over a FakeDrafts table, so the real `create` can be driven without a database."""

    def __init__(self, table, fail=None):
        super().__init__()
        self.table, self.fail, self.log = table, fail, []
        self.commits = self.rollbacks = 0
        self.closed = False

    def insert_row(self, *args):
        self.table.insert_row(*args)

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in ("LEDGERLINE_DSN", "LEDGERLINE_WRITER_USER", "LEDGERLINE_WRITER_PASSWORD"):
        monkeypatch.setenv(name, "x")


def test_one_draft_per_key_in_the_fake_table():
    table = drafts.FakeDrafts()
    table.insert_row("DS-1", 1, Decimal("1.00"), "k", "W")
    with pytest.raises(oracledb.IntegrityError) as error:
        table.insert_row("DS-1", 1, Decimal("1.00"), "k", "W")
    assert drafts.is_unique_violation(error.value)


def test_a_retry_returns_the_same_draft():
    table = drafts.FakeDrafts()
    first = table.create("s1", ORDER, 1)
    again = table.create("s1", ORDER, 1)
    assert first == again and len(table.rows) == 1


def test_a_different_line_is_a_different_draft():
    table = drafts.FakeDrafts()
    one, two = table.create("s1", ORDER, 1), table.create("s1", ORDER, 2)
    assert one["key"] != two["key"] and one["req_id"] != two["req_id"] and len(table.rows) == 2


def test_a_different_session_is_a_different_draft():
    table = drafts.FakeDrafts()
    assert table.create("s1", ORDER, 1)["key"] != table.create("s2", ORDER, 1)["key"]


def test_the_key_is_a_sha256_hex_of_the_three():
    key = drafts.idempotency_key("s1", "DS-1", 1)
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert key == drafts.idempotency_key("s1", "DS-1", 1)
    assert key != drafts.idempotency_key("s1", "DS-1", 2)


def test_the_amount_comes_from_money_and_is_a_decimal():
    table = drafts.FakeDrafts()
    assert table.create("s", ORDER, 1)["amount"] == Decimal("120.00")
    second = table.create("s", ORDER, 2)["amount"]
    assert second == Decimal("48.01") and isinstance(second, Decimal)  # first item gets the odd cent


def test_a_float_amount_raises():
    order = {"number": "DS-1", "lines": [{"line": 1, "unit_price": 10.5, "quantity": 1, "tax": Decimal("1.00")}]}
    with pytest.raises(TypeError):
        drafts.FakeDrafts().create("s", order, 1)


def test_an_unknown_line_raises():
    with pytest.raises(ValueError, match="no line 9"):
        drafts.FakeDrafts().create("s", ORDER, 9)


def test_the_status_written_is_w():
    assert drafts.FakeDrafts().create("s", ORDER, 1)["status"] == "W"
    assert drafts.WAITING == "W"


def test_no_status_letter_a_or_r_is_written():
    assert not re.search(r"""["'][AR]["']""", SOURCE)


def test_the_only_write_statement_is_one_insert_into_the_holding_table():
    statements = [drafts.INSERT, drafts.BY_KEY]
    writes = [s for s in statements if re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|ALTER|CREATE)\b", s, re.IGNORECASE)]
    assert writes == [drafts.INSERT]
    assert re.match(r"\s*INSERT INTO LEDGERLINE\.LL_RTN_REQ_STG \(", drafts.INSERT)
    assert re.findall(r"\bLL_\w+", drafts.INSERT) == ["LL_RTN_REQ_STG"]


def test_the_module_has_no_update_delete_or_merge():
    tree = ast.parse(SOURCE)
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    for text in strings:
        assert not re.search(r"\b(UPDATE|DELETE|MERGE|DROP|TRUNCATE)\b", text, re.IGNORECASE), text


def test_the_insert_does_not_name_req_id_and_uses_binds():
    assert "REQ_ID" not in drafts.INSERT
    assert re.findall(r":\w+", drafts.INSERT) == [":order_no", ":line_no", ":amount", ":req_key", ":status"]


def test_the_writer_account_is_used_only_here():
    others = [p for p in Path(".").glob("*.py") if p.name != "drafts.py" and not p.name.startswith("test_")]
    for path in others:
        text = path.read_text()
        assert "ledgerline_writer" not in text or path.name == "config.py", path.name


def test_create_inserts_commits_and_closes():
    table, seen = drafts.FakeDrafts(), {}
    conn = Connection(table)

    def connect(**kwargs):
        seen.update(kwargs)
        return conn
    draft = drafts.create("s", ORDER, 1, connect=connect)
    assert seen["user"] == "x" and draft["status"] == "W" and draft["amount"] == Decimal("120.00")
    assert conn.commits == 1 and conn.closed
    inserts = [b for sql, b in conn.log if sql == drafts.INSERT]
    assert len(inserts) == 1 and inserts[0]["status"] == "W" and "req_id" not in inserts[0]


def test_create_on_a_unique_violation_reads_the_existing_draft_and_writes_nothing_more():
    table = drafts.FakeDrafts()
    first = drafts.create("s", ORDER, 1, connect=lambda **_: Connection(table))
    conn = Connection(table)
    again = drafts.create("s", ORDER, 1, connect=lambda **_: conn)
    assert again == first and len(table.rows) == 1
    assert conn.commits == 0 and conn.rollbacks == 1 and conn.closed


class Err:
    def __init__(self, code):
        self.code = code


@pytest.mark.parametrize("error", [oracledb.IntegrityError(Err(2290)), oracledb.DatabaseError(Err(12541)),
                                   oracledb.OperationalError(Err(3114))])
def test_any_other_database_error_is_raised_not_swallowed(error):
    conn = Connection(drafts.FakeDrafts(), fail=error)
    with pytest.raises(oracledb.Error):
        drafts.create("s", ORDER, 1, connect=lambda **_: conn)
    assert conn.closed and not conn.table.rows


def test_a_unique_violation_of_another_code_is_not_ours():
    assert not drafts.is_unique_violation(oracledb.IntegrityError(Err(2290)))
    assert not drafts.is_unique_violation(ValueError("ORA-00001"))
