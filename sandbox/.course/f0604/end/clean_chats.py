"""Clean the old chats before any model or report reads them."""
import json
import re

import pandas as pd

from ledgerline import connection

EMAIL = r"[\w.+-]+@[\w-]+\.\w+"
CARD = r"\d{4} \d{4} \d{4} \d{4}"
PHONE = r"[+0][\d ]{8,}\d"


def report(chats, title):
    """What a model would see in these chats."""
    text = chats["transcript"]
    print(title, len(chats), "chats")
    print("  the same chat twice:", chats["number"].duplicated().sum())
    print("  times not in UTC:", (chats["zone"] != "UTC").sum())
    print("  no market:", chats["market"].isna().sum())
    print("  emails:", text.str.contains(EMAIL).sum())
    print("  phone numbers:", text.str.contains(PHONE).sum())
    print("  card numbers:", text.str.contains(CARD).sum())


def mask(text):
    """Personal data out, a label in its place."""
    text = re.sub(CARD, "[card number removed]", text)
    text = re.sub(EMAIL, "[email]", text)
    text = re.sub(PHONE, "[phone]", text)
    return re.sub(r"^[^:]+:", "Customer:", text)


with open("data/chats.json") as f:
    pulled = pd.DataFrame(json.load(f).values())
pulled["zone"] = "UTC"
business = pd.read_csv("data/business_view.csv")
business["zone"] = "Europe/Berlin"
chats = pd.concat([pulled, business])
chats["market"] = chats["u_market"].replace("", None)
report(chats, "Before:")

chats = chats.drop_duplicates("number")

berlin = chats["zone"] == "Europe/Berlin"
local = pd.to_datetime(chats.loc[berlin, "opened_at"])
utc = local.dt.tz_localize("Europe/Berlin").dt.tz_convert("UTC")
chats.loc[berlin, "opened_at"] = utc.dt.strftime("%Y-%m-%d %H:%M:%S")
chats.loc[berlin, "zone"] = "UTC"

sql = "SELECT email_addr, mkt_cd FROM ledgerline.ll_cust"
accounts = dict(connection.cursor().execute(sql).fetchall())
chats["market"] = chats["market"].fillna(chats["opened_for"].map(accounts))

chats["transcript"] = chats["transcript"].map(mask)
report(chats, "After:")

clean = chats[["number", "opened_at", "market", "transcript"]]
clean.to_csv("data/chats_clean.csv", index=False)
print("saved", len(clean), "chats to data/chats_clean.csv")
