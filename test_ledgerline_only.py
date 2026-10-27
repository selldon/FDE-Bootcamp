"""Fast test of the rule in docs/adr/0001: only ledgerline.py and drafts.py may open a connection to Ledgerline.

ledgerline.py is the middleware (the read-only account); drafts.py is the one writer (the account that inserts a return draft).
A new module that opens its own connection fails here. Two tools for people open one too, and are named below so the list is
honest: probe_live.py (a look at the real systems) and doctor.py (a health check that counts the orders). No test, no job and no
module of the chat opens one. The check reads the source, so it needs no network and no database.
"""
import ast
import os
from pathlib import Path

ROOT = Path(__file__).parent

ALLOWED = {"ledgerline.py", "drafts.py"}
TOOLS_FOR_PEOPLE = {"probe_live.py", "doctor.py"}  # run by a person, never by the chat, a job or CI

DRIVERS = {"oracledb", "cx_Oracle"}
OPENERS = {"connect", "connect_async", "create_pool", "create_pool_async"}
SKIP_DIRS = {"sandbox", "builds", "node_modules", "widget", "__pycache__"}  # as pyproject.toml: the labs are not the product


def openings(source):
    """Where a source file opens (or can open) a connection with an Oracle driver: a list of (line, what)."""
    found = []
    aliases = set()  # the names the driver module goes by in this file
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {a.asname or a.name for a in node.names if a.name.split(".")[0] in DRIVERS}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in DRIVERS:
            for a in node.names:
                if a.name in OPENERS or a.name == "*":
                    found.append((node.lineno, f"from {node.module} import {a.name}"))
        elif isinstance(node, ast.Call):  # importlib.import_module("oracledb"), __import__("oracledb")
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in {"import_module", "__import__"} and node.args and isinstance(node.args[0], ast.Constant) \
                    and str(node.args[0].value).split(".")[0] in DRIVERS:
                found.append((node.lineno, f"{name}({node.args[0].value!r})"))
    for node in ast.walk(tree):
        # oracledb.connect(...) and also the bare reference `connect=oracledb.connect`, which is how ledgerline.py takes it
        if isinstance(node, ast.Attribute) and node.attr in OPENERS and isinstance(node.value, ast.Name) \
                and node.value.id in aliases:
            found.append((node.lineno, f"{node.value.id}.{node.attr}"))
    return sorted(found)


def python_files():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(".py"):
                yield Path(folder) / name


def test_only_the_middleware_and_the_writer_open_a_connection_to_ledgerline():
    offenders = {}
    for path in python_files():
        where = openings(path.read_text())
        if where and path.name not in ALLOWED | TOOLS_FOR_PEOPLE:
            offenders[str(path.relative_to(ROOT))] = where
    assert not offenders, (
        "These files open a connection to Ledgerline. Only ledgerline.py (reads) and drafts.py (the draft) may; "
        f"see docs/adr/0001: {offenders}")


def test_the_two_that_may_are_found_so_the_check_is_not_empty():
    for name in ALLOWED:
        assert openings((ROOT / name).read_text()), f"{name} no longer opens a connection: update this test and the ADR"


def test_the_tools_for_people_are_not_a_way_around_the_rule():
    # the tools are named so the list is honest; the chat, the jobs and the tests must not import them
    for path in python_files():
        if path.name in TOOLS_FOR_PEOPLE:
            continue
        tree = ast.parse(path.read_text())
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not imported & {"probe_live", "doctor"}, f"{path.name} imports a tool for people"


# ---- the check itself: it must catch each way of opening one ---------------------------------------------------

def test_the_check_catches_a_call_a_bare_reference_an_alias_and_a_from_import():
    assert openings("import oracledb\nconn = oracledb.connect(dsn='x')")
    assert openings("import oracledb\ndef f(connect=oracledb.connect): pass")
    assert openings("import oracledb as ora\nora.create_pool()")
    assert openings("from oracledb import connect")
    assert openings("import importlib\nimportlib.import_module('oracledb')")
    assert openings("import cx_Oracle\ncx_Oracle.connect()")


def test_the_check_lets_a_module_use_the_drivers_errors_and_the_middleware():
    assert not openings("import oracledb\ntry:\n    pass\nexcept oracledb.Error:\n    pass")  # refunds.py does this
    assert not openings("import ledgerline\nledgerline.order_lines('DS-1', 'a@b.c')")
    assert not openings("import psycopg\npsycopg.connect('x')")  # our own PostgreSQL is not Ledgerline
