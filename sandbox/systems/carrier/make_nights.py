"""Builds the carrier's nightly files on its SFTP server (the stand-in in systems/compose.yaml).

    python systems/carrier/make_nights.py      writes systems/carrier/upload/carrier-2026-10-20.csv, -21, -22

The agreement with the carrier: one UTF-8 CSV a night, the columns tracking, status, place, date (ISO dates). The nights
of 20 and 21 October keep it (21 October is the sandbox's data/carrier.csv). On 22 October the carrier changed its
system without telling anyone: a new column, pickup_point, sits in the middle, and the file is written in Latin-1, so a
German place name like Köln breaks for every UTF-8 reader.
"""
import csv
from pathlib import Path

HERE = Path(__file__).parent
rows = list(csv.DictReader((HERE.parent.parent / "data" / "carrier.csv").open(encoding="utf-8")))
out = HERE / "upload"
out.mkdir(exist_ok=True)


def write(name, rows, columns, encoding):
    with (out / name).open("w", encoding=encoding, newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)


# 20 October: one day earlier, the parcels still on their way
night20 = []
for r in rows:
    r = dict(r)
    if r["date"] == "2026-10-21":
        r["date"] = "2026-10-20"
        if r["status"] == "out for delivery":
            r["status"] = "in transit"
    night20.append(r)
write("carrier-2026-10-20.csv", night20, ["tracking", "status", "place", "date"], "utf-8")

# 21 October: the agreed shape, exactly the sandbox's data/carrier.csv
write("carrier-2026-10-21.csv", rows, ["tracking", "status", "place", "date"], "utf-8")

# 22 October: the parcels move on, and the carrier's new export changes the shape and the encoding
moves = {
    "EP-7718204": ("out for delivery", "Locker 4, Leeds Station", "Leeds depot"),
    "EP-7718402": ("delivered", "Packstation 112, Köln", "front door"),
    "EP-7718403": ("delivered", "Packstation 112, Köln", "front door"),
    "EP-7718311": ("out for delivery", "", "Newark hub"),
    "EP-7718241": ("delivered", "", "front door"),
}
night22 = []
for r in rows:
    status, pickup, place = moves.get(r["tracking"], (r["status"], "", r["place"]))
    date = "2026-10-22" if r["tracking"] in moves or r["date"] == "2026-10-21" else r["date"]
    night22.append({"tracking": r["tracking"], "status": status, "pickup_point": pickup, "place": place, "date": date})
write("carrier-2026-10-22.csv", night22, ["tracking", "status", "pickup_point", "place", "date"], "latin-1")

print("nights:", ", ".join(sorted(p.name for p in out.glob("carrier-*.csv"))))
