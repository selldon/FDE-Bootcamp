"""Look at the real systems, read-only: what tables, files and columns they have.

A tool for people, not a test. It writes nothing anywhere. Emails are masked.
"""
import re
import stat

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


if __name__ == "__main__":
    for step in (ledgerline, carrier, store):
        try:
            step()
        except Exception as error:  # noqa: BLE001 - one system down must not hide the others
            print(f"!! {step.__name__}: {type(error).__name__}: {error}")
