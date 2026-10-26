"""The carrier's nightly file: download it, check it, then let it land."""
import csv
import os
import shutil
import sys
from datetime import date

import paramiko
from dotenv import load_dotenv

from tools import delivery_status

load_dotenv()
COLUMNS = ["tracking", "status", "place", "date"]
STATUSES = ["label created", "in transit", "out for delivery",
            "delivered", "returned"]
MIN_ROWS = 30


def download(name):
    """Copy a file from the carrier's server to our inbox: the one we
    name, or the newest."""
    host, port = os.environ["CARRIER_HOST"], int(os.environ["CARRIER_PORT"])
    transport = paramiko.Transport((host, port))
    transport.connect(username=os.environ["CARRIER_USER"],
                      password=os.environ["CARRIER_PASSWORD"])
    sftp = paramiko.SFTPClient.from_transport(transport)
    if name is None:
        name = sorted(sftp.listdir("upload"))[-1]
    os.makedirs("data/inbox", exist_ok=True)
    sftp.get("upload/" + name, "data/inbox/" + name)
    transport.close()
    return name


def problems(path):
    """Everything wrong with the file. An empty list means it may land."""
    found = []
    with open(path, "rb") as f:
        header = f.readline().decode().strip().split(",")
        body = f.read()
    if header != COLUMNS:
        found.append(f"columns {header}")
    try:
        lines = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        found.append(f"not UTF-8 ({error.reason} at byte {error.start})")
        return found
    for row in csv.DictReader(lines, fieldnames=header):
        if row["status"] not in STATUSES:
            found.append(f"{row['tracking']}: unknown status {row['status']}")
        try:
            date.fromisoformat(row["date"])
        except ValueError:
            found.append(f"{row['tracking']}: no real date {row['date']}")
    if len(lines) < MIN_ROWS:
        found.append(f"only {len(lines)} rows")
    return found


name = None
if len(sys.argv) > 1:
    name = sys.argv[1]
name = download(name)
found = problems("data/inbox/" + name)
if found:
    os.makedirs("data/rejected", exist_ok=True)
    shutil.move("data/inbox/" + name, "data/rejected/" + name)
    print("REJECTED", name, "-", "; ".join(found))
else:
    shutil.copy("data/inbox/" + name, "data/carrier.csv")
    print("landed", name)
print("delivery tool:", delivery_status("EP-7718204"))
