"""The carrier's nightly file: the only module that imports paramiko.

Files are `upload/carrier-YYYY-MM-DD.csv`, cp1252, and the columns differ between files, so
rows are read by header name. The news has a date and no time of day (docs/live-shapes.md).
A bad line is an error with its line number, never skipped quietly.
"""
import csv
import io
import re
from contextlib import contextmanager
from datetime import date

import paramiko

import config

FOLDER = "upload"
NAME = re.compile(r"^carrier-(\d{4}-\d{2}-\d{2})\.csv$")
ENCODING = "cp1252"
REQUIRED = ("tracking", "status", "place", "date")


class CarrierError(Exception):
    """The carrier's data cannot be used; the message says why."""


class SftpFiles:
    """The small interface to a folder of files: the real server and the fake both have it."""

    def __init__(self, sftp):
        self.sftp = sftp

    def names(self):
        return self.sftp.listdir(FOLDER)

    def read(self, name):
        with self.sftp.open(f"{FOLDER}/{name}", "rb") as f:
            return f.read()


@contextmanager
def connect():
    """Opens the real server with the settings (read only: list and read); closes it afterwards."""
    s = config.carrier()
    transport = paramiko.Transport((s["host"], s["port"]))
    try:
        transport.connect(username=s["user"], password=s["password"])
        sftp = paramiko.SFTPClient.from_transport(transport)
        yield SftpFiles(sftp)
    finally:
        transport.close()


def newest_name(files):
    """The name of the file with the latest date in its name; an empty folder is an error."""
    dated = [(m.group(1), n) for n in files.names() if (m := NAME.match(n))]
    if not dated:
        raise CarrierError(f"no carrier-YYYY-MM-DD.csv file in {FOLDER}/")
    return max(dated)[1]


def parse(data, source="carrier file"):
    """Rows of one file as dicts: tracking, status, place, pickup_point (may be ''), date."""
    reader = csv.reader(io.StringIO(data.decode(ENCODING), newline=""))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        raise CarrierError(f"{source}: the file is empty") from None
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise CarrierError(f"{source}: line 1: missing columns {', '.join(missing)}")
    rows = []
    for fields in reader:
        line = reader.line_num
        if not fields:
            continue  # a blank line carries nothing
        if len(fields) != len(header):
            raise CarrierError(f"{source}: line {line}: {len(fields)} fields, expected {len(header)}")
        row = dict(zip(header, (f.strip() for f in fields)))
        for column in ("tracking", "status", "place"):
            if not row[column]:
                raise CarrierError(f"{source}: line {line}: empty {column}")
        try:
            row["date"] = date.fromisoformat(row["date"])
        except ValueError:
            raise CarrierError(f"{source}: line {line}: bad date {row['date']!r}") from None
        row.setdefault("pickup_point", "")
        rows.append(row)
    return rows


def newest_rows(files):
    """(file name, rows) of the newest file."""
    name = newest_name(files)
    return name, parse(files.read(name), name)


def newest_news(rows):
    """The date of the newest news in the rows, or None."""
    return max((r["date"] for r in rows), default=None)
