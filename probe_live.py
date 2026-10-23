"""Look at the real systems, read-only: what tables, files and columns they have.

A tool for people, not a test. It writes nothing anywhere. Emails are masked.
"""
import base64
import json
import re
import stat
import sys
import urllib.error
import urllib.request

import oracledb
import paramiko
import psycopg

import config

SAMPLE_ROWS = 3
HEAD_LINES = 5
IDENT = re.compile(r"^[A-Z0-9_$#]+$")


def mask(value):
    """Hide the local part of an email; leave everything else."""
    if isinstance(value, str) and "@" in value:
        return value[:1] + "***@" + value.split("@", 1)[1]
    return value


def ledgerline():
    print("== Ledgerline (read-only account)")
    conn = oracledb.connect(**config.ledgerline())
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute("SELECT username FROM all_users WHERE oracle_maintained = 'N'")
    owners = [r[0] for r in cur.fetchall()]
    for owner in owners:
        cur.execute("SELECT table_name FROM all_tables WHERE owner = :o "
                    "ORDER BY table_name", o=owner)
        for (table,) in cur.fetchall():
            if not (IDENT.match(owner) and IDENT.match(table)):
                print(f"-- skipped odd name {owner}.{table}")
                continue
            cur.execute("SELECT column_name, data_type FROM all_tab_columns "
                        "WHERE owner = :o AND table_name = :t "
                        "ORDER BY column_id", o=owner, t=table)
            columns = cur.fetchall()
            cur.execute(f"SELECT COUNT(*) FROM {owner}.{table}")
            print(f"\n{owner}.{table}: {cur.fetchone()[0]} rows")
            print("  columns:", ", ".join(f"{c} {t}" for c, t in columns))
            cur.execute(f"SELECT * FROM {owner}.{table} "
                        f"FETCH FIRST {SAMPLE_ROWS} ROWS ONLY")
            for row in cur.fetchall():
                print("  sample:", [mask(v) for v in row])
    conn.rollback()
    conn.close()


def carrier():
    print("\n== Carrier SFTP server")
    settings = config.carrier()
    transport = paramiko.Transport((settings["host"], settings["port"]))
    transport.connect(username=settings["user"],
                      password=settings["password"])
    sftp = paramiko.SFTPClient.from_transport(transport)
    assert sftp is not None
    plain = []
    for attr in sftp.listdir_attr("."):
        is_dir = stat.S_ISDIR(attr.st_mode or 0)
        print(f"  {'dir ' if is_dir else 'file'} {attr.filename}  "
              f"{attr.st_size} bytes  mtime {attr.st_mtime}")
        # one level down: the files may sit in a folder such as upload/
        for inner in sftp.listdir_attr(attr.filename) if is_dir else [attr]:
            path = f"{attr.filename}/{inner.filename}" if is_dir else inner.filename
            if is_dir:
                print(f"       {path}  {inner.st_size} bytes  mtime {inner.st_mtime}")
            if not stat.S_ISDIR(inner.st_mode or 0):
                plain.append((inner.st_mtime or 0, path))
    if plain:
        newest = max(plain)[1]
        print(f"\nnewest file: {newest}")
        with sftp.open(newest) as f:
            raw = f.read()
        try:
            text, encoding = raw.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, encoding = raw.decode("cp1252"), "cp1252 (not utf-8)"
        lines = text.splitlines()
        print(f"encoding: {encoding}, {len(lines)} lines")
        for line in lines[:HEAD_LINES]:
            print("  |", mask(line))
    sftp.close()
    transport.close()


def store():
    print("\n== Our PostgreSQL (order store)")
    with psycopg.connect(config.store_url()) as conn:
        conn.read_only = True
        rows = conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            "ORDER BY 1, 2").fetchall()
    for schema, table in rows:
        print(f"  {schema}.{table}")
    if not rows:
        print("  (no tables yet)")


BUILD3_TABLES = ["LL_CUST", "LL_ORD_HDR", "LL_ORD_LN", "LL_SHPMT", "LL_RTN_REQ_STG"]
MAX_CODES = 12


def ledgerline_build3():
    """Build 3: names, types and counts of the tables a return needs. No rows, no emails."""
    print("== Ledgerline, Build 3 (read-only account; column names, counts and code values only)")
    conn = oracledb.connect(**config.ledgerline())
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    for table in BUILD3_TABLES:
        cur.execute("SELECT owner, column_name, data_type, data_precision, data_scale "
                    "FROM all_tab_columns WHERE table_name = :t ORDER BY owner, column_id", t=table)
        columns = cur.fetchall()
        if not columns:
            print(f"\n{table}: not visible to the reader")
            continue
        owner = columns[0][0]
        if not (IDENT.match(owner) and IDENT.match(table)):
            print(f"\n-- skipped odd name {owner}.{table}")
            continue
        cur.execute(f"SELECT COUNT(*) FROM {owner}.{table}")
        print(f"\n{owner}.{table}: {cur.fetchone()[0]} rows")
        for _, name, kind, precision, scale in columns:
            size = f"({precision},{scale})" if precision is not None else ""
            line = f"  {name} {kind}{size}"
            # code columns (..._CD, ..._TYP...): the distinct values are the mapping we need
            if name.endswith("_CD") and IDENT.match(name):
                cur.execute(f"SELECT {name}, COUNT(*) FROM {owner}.{table} "
                            f"GROUP BY {name} ORDER BY 2 DESC FETCH FIRST {MAX_CODES} ROWS ONLY")
                line += "  values: " + ", ".join(f"{v!r} x{n}" for v, n in cur.fetchall())
            print(line)
    cur.execute("SELECT constraint_name, constraint_type, table_name FROM all_constraints "
                "WHERE table_name = 'LL_RTN_REQ_STG' AND constraint_type IN ('P', 'U')")
    for name, kind, table in cur.fetchall():
        cur.execute("SELECT column_name FROM all_cons_columns WHERE constraint_name = :c "
                    "ORDER BY position", c=name)
        print(f"\n{table} {'primary' if kind == 'P' else 'unique'} key {name}: "
              + ", ".join(r[0] for r in cur.fetchall()))
    conn.rollback()
    conn.close()


def get(path):
    """One GET to ServiceNow with basic auth. Returns (json, headers); never any other verb."""
    settings = config.servicenow()
    token = base64.b64encode(f"{settings['user']}:{settings['password']}".encode()).decode()
    request = urllib.request.Request(settings["url"] + path, method="GET", headers={
        "Authorization": f"Basic {token}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response), response.headers


def servicenow_build3():
    """Build 3: is ServiceNow reachable, and what fields do approval tasks and cases have. GET only."""
    print("\n== ServiceNow (GET only; field names and counts, no values)")
    settings = config.servicenow()
    print(f"  url {settings['url']}  account {settings['user']}")
    for table in ("sc_task", "interaction"):
        try:
            body, headers = get(f"/api/now/table/{table}?sysparm_limit=1&sysparm_exclude_reference_link=true")
        except urllib.error.HTTPError as error:
            print(f"  {table}: HTTP {error.code}")
            continue
        rows = body.get("result", [])
        total = headers.get("X-Total-Count", f"{len(rows)} (first page)")
        print(f"  {table}: {total} rows")
        if rows:
            print("    fields:", ", ".join(sorted(rows[0])))
        else:
            print("    no rows, so no field names to show")
        try:
            fields, _ = get(f"/api/now/table/sys_dictionary?sysparm_query=name={table}"
                            "&sysparm_fields=element,internal_type,mandatory&sysparm_limit=200")
            for f in fields.get("result", []):
                if f.get("element"):
                    print(f"    dictionary: {f['element']} {f.get('internal_type', '')} "
                          f"{'mandatory' if f.get('mandatory') == 'true' else ''}".rstrip())
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            print(f"    dictionary: not available ({error})")


if __name__ == "__main__":
    steps = (ledgerline_build3, servicenow_build3) if sys.argv[1:] == ["build3"] \
        else (ledgerline, carrier, store)
    for step in steps:
        try:
            step()
        except Exception as error:  # noqa: BLE001 - one system down must not hide the others
            print(f"!! {step.__name__}: {type(error).__name__}: {error}")
