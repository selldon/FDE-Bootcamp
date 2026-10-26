"""Builds the init scripts of Ledgerline, DemoStore's ERP (Oracle, no API), from the orders the labs use.

    python systems/ledgerline/make_sql.py    writes systems/ledgerline/init/01_schema.sql, 02_data.sql, 03_reader.sql,
                                             04_staging.sql

The scripts run once, when the Oracle container starts with an empty database (gvenzl/oracle-free runs every file in
/container-entrypoint-initdb.d). The names are the ERP's own, short and old (LL_ORD_HDR, ORD_STAT_CD): the course reads
someone else's schema, as an FDE does at a client.
"""
import json
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
orders = json.loads((HERE.parent.parent / "data" / "orders.json").read_text())

CURRENCY = {"UK": "GBP", "US": "USD", "DE": "EUR", "FR": "EUR", "IT": "EUR"}
TAX = {"UK": 0.20, "US": 0.08, "DE": 0.19, "FR": 0.20, "IT": 0.22}
STATUS = {"processing": "N", "partly shipped": "S", "shipped": "F", "delivered": "D"}
PRICE = {  # one price per item, in the order's currency
    "laptop": 1299.00, "pro laptop": 1749.00, "monitor": 329.00, "graphics card": 699.00, "router": 129.00,
    "ssd": 89.00, "keyboard": 79.00, "mouse": 39.00, "power supply": 119.00, "headset": 99.00, "tablet": 449.00,
    "webcam": 69.00, "dock": 189.00, "printer": 249.00, "speaker": 129.00, "drive": 99.00,
}
BUSINESS = {"hannah.weber@example.com", "ines.dubois@example.com"}
# the order of the labeled chat "I ordered a router and an SSD on the 3rd and only the router came": two parcels, days apart
ORDERED = {"DS-20468": date(2026, 10, 3)}
SHIPPED = {"DS-20468": [date(2026, 10, 14), date(2026, 10, 20)]}


def price_of(item):
    low = item.lower()
    for key in sorted(PRICE, key=len, reverse=True):
        if key in low:
            return PRICE[key]
    return 99.00


def sku_of(item):
    words = [w for w in item.replace("-", " ").split() if w.isalnum()]
    return "-".join(w[:3].upper() for w in words)[:20]


def d(x):
    return f"DATE '{x.isoformat()}'"


def q(s):
    return "'" + str(s).replace("'", "''") + "'"


schema = """-- Ledgerline, DemoStore's ERP: orders, their lines, shipments and invoices (owner LEDGERLINE)
ALTER SESSION SET CONTAINER = FREEPDB1;
ALTER SESSION SET CURRENT_SCHEMA = LEDGERLINE;

CREATE TABLE LL_CUST (
  CUST_ID      NUMBER(10)    PRIMARY KEY,
  EMAIL_ADDR   VARCHAR2(120) NOT NULL UNIQUE,
  CUST_NM      VARCHAR2(80)  NOT NULL,
  MKT_CD       VARCHAR2(2)   NOT NULL,
  CUST_TYP_CD  CHAR(1)       NOT NULL,          -- C consumer, B DemoStore Business
  CRT_DT       DATE          NOT NULL
);

CREATE TABLE LL_ORD_HDR (
  ORD_NO       VARCHAR2(12)  PRIMARY KEY,
  CUST_ID      NUMBER(10)    NOT NULL REFERENCES LL_CUST,
  ORD_DT       DATE          NOT NULL,
  ORD_STAT_CD  CHAR(1)       NOT NULL,          -- N new, S split (part shipped), F fulfilled, D delivered, X cancelled
  PROM_DT      DATE,                            -- delivery date promised to the customer
  CURR_CD      CHAR(3)       NOT NULL,
  ORD_TOT      NUMBER(12,2)  NOT NULL
);

CREATE TABLE LL_ORD_LN (
  ORD_NO       VARCHAR2(12)  NOT NULL REFERENCES LL_ORD_HDR,
  LN_NO        NUMBER(3)     NOT NULL,
  SKU_CD       VARCHAR2(20)  NOT NULL,
  ITEM_DESC    VARCHAR2(100) NOT NULL,
  QTY          NUMBER(5)     NOT NULL,
  UNIT_PRC     NUMBER(10,2)  NOT NULL,
  TAX_AMT      NUMBER(10,2)  NOT NULL,
  PRIMARY KEY (ORD_NO, LN_NO)
);

CREATE TABLE LL_SHPMT (
  SHPMT_ID     NUMBER(10)    PRIMARY KEY,
  ORD_NO       VARCHAR2(12)  NOT NULL,
  LN_NO        NUMBER(3)     NOT NULL,
  CARR_CD      VARCHAR2(10)  NOT NULL,
  TRK_NO       VARCHAR2(20)  NOT NULL,
  SHIP_DT      DATE          NOT NULL,
  FOREIGN KEY (ORD_NO, LN_NO) REFERENCES LL_ORD_LN
);

CREATE TABLE LL_INV_HDR (
  INV_NO       VARCHAR2(14)  PRIMARY KEY,
  ORD_NO       VARCHAR2(12)  NOT NULL REFERENCES LL_ORD_HDR,
  INV_DT       DATE          NOT NULL,
  NET_AMT      NUMBER(12,2)  NOT NULL,
  TAX_AMT      NUMBER(12,2)  NOT NULL,
  CURR_CD      CHAR(3)       NOT NULL
);
"""

rows, cust_ids = [], {}
for o in orders:
    if o["customer"] not in cust_ids:
        cid = 10400 + len(cust_ids) + 1
        cust_ids[o["customer"]] = cid
        name = " ".join(p.capitalize() for p in o["customer"].split("@")[0].split("."))
        typ = "B" if o["customer"] in BUSINESS else "C"
        rows.append(f"INSERT INTO LL_CUST VALUES ({cid}, {q(o['customer'])}, {q(name)}, {q(o['market'])}, '{typ}', {d(date(2025, 3, 1) + timedelta(days=cid % 200))});")

shp, inv = 70001, 0
for o in orders:
    promised = date.fromisoformat(o["promised"])
    ordered = ORDERED.get(o["number"], promised - timedelta(days=6))
    tax = TAX[o["market"]]
    lines = [(i + 1, item, price_of(item)) for i, item in enumerate(o["items"])]
    net = round(sum(p for _, _, p in lines), 2)
    total = round(net * (1 + tax), 2)
    rows.append(f"INSERT INTO LL_ORD_HDR VALUES ({q(o['number'])}, {cust_ids[o['customer']]}, {d(ordered)}, '{STATUS[o['status']]}', {d(promised)}, '{CURRENCY[o['market']]}', {total:.2f});")
    for n, item, p in lines:
        rows.append(f"INSERT INTO LL_ORD_LN VALUES ({q(o['number'])}, {n}, {q(sku_of(item))}, {q(item)}, 1, {p:.2f}, {round(p * tax, 2):.2f});")
    # one parcel per line when there are as many tracking numbers as lines, else one parcel for the whole order
    for k, trk in enumerate(o["tracking"]):
        targets = [k + 1] if len(o["tracking"]) == len(lines) else [n for n, _, _ in lines]
        shipped = SHIPPED[o["number"]][k] if o["number"] in SHIPPED else ordered + timedelta(days=1)
        for ln in targets:
            rows.append(f"INSERT INTO LL_SHPMT VALUES ({shp}, {q(o['number'])}, {ln}, 'EP', {q(trk)}, {d(shipped)});")
            shp += 1
    if o["tracking"]:
        inv += 1
        rows.append(f"INSERT INTO LL_INV_HDR VALUES ('INV-{26000 + inv}', {q(o['number'])}, {d(ordered + timedelta(days=1))}, {net:.2f}, {round(total - net, 2):.2f}, '{CURRENCY[o['market']]}');")

data = "-- Ledgerline test data: the orders of the labs\nALTER SESSION SET CONTAINER = FREEPDB1;\nALTER SESSION SET CURRENT_SCHEMA = LEDGERLINE;\n\n" + "\n".join(rows) + "\nCOMMIT;\n"

reader = """-- LL_READER: the read-only account Ledgerline's owner gives us (no writes, no other tables)
ALTER SESSION SET CONTAINER = FREEPDB1;
-- "reader" is a test password of the local sandbox
CREATE USER LL_READER IDENTIFIED BY "reader";
GRANT CREATE SESSION TO LL_READER;
GRANT SELECT ON LEDGERLINE.LL_CUST TO LL_READER;
GRANT SELECT ON LEDGERLINE.LL_ORD_HDR TO LL_READER;
GRANT SELECT ON LEDGERLINE.LL_ORD_LN TO LL_READER;
GRANT SELECT ON LEDGERLINE.LL_SHPMT TO LL_READER;
GRANT SELECT ON LEDGERLINE.LL_INV_HDR TO LL_READER;
"""

staging = """-- LL_RTN_REQ_STG: the staging table Ledgerline's owner made for return drafts from other programs (the assistant's
-- middleware). Nothing in it is official: Ledgerline's own job checks each approved draft and books it in the real tables.
ALTER SESSION SET CONTAINER = FREEPDB1;

CREATE TABLE LEDGERLINE.LL_RTN_REQ_STG (
  REQ_ID       NUMBER(10)    GENERATED ALWAYS AS IDENTITY (START WITH 1001) PRIMARY KEY,
  ORD_NO       VARCHAR2(12)  NOT NULL,
  LN_NO        NUMBER(3)     NOT NULL,
  RFND_AMT     NUMBER(10,2)  NOT NULL,
  REQ_KEY      VARCHAR2(64)  UNIQUE,                 -- the sender's idempotency key: one draft per key
  STG_STAT_CD  CHAR(1)       DEFAULT 'W' NOT NULL,   -- W waiting, A approved, R rejected (set by Ledgerline's job)
  CRT_TS       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

-- sandbox only: Ledgerline on a sale day. Each write into the staging table waits SLOW_WRITE_SEC seconds (0 = off);
-- the return lesson (FDE 1-7-7) sets 3 before its take and 0 after it
CREATE TABLE LEDGERLINE.LL_SBX_CFG (
  CFG_NM       VARCHAR2(30)  PRIMARY KEY,
  CFG_VAL      NUMBER        NOT NULL
);
INSERT INTO LEDGERLINE.LL_SBX_CFG VALUES ('SLOW_WRITE_SEC', 0);
COMMIT;

CREATE OR REPLACE TRIGGER LEDGERLINE.LL_RTN_REQ_STG_SLOW BEFORE INSERT ON LEDGERLINE.LL_RTN_REQ_STG FOR EACH ROW
DECLARE
  secs NUMBER;
BEGIN
  SELECT CFG_VAL INTO secs FROM LEDGERLINE.LL_SBX_CFG WHERE CFG_NM = 'SLOW_WRITE_SEC';
  IF secs > 0 THEN DBMS_SESSION.SLEEP(secs); END IF;
END;
/

-- LL_WRITER: the account for the staging table only, the one write Ledgerline's owner agreed to (no updates, no deletes,
-- no other tables). "writer" is a test password of the local sandbox
CREATE USER LL_WRITER IDENTIFIED BY "writer";
GRANT CREATE SESSION TO LL_WRITER;
GRANT INSERT, SELECT ON LEDGERLINE.LL_RTN_REQ_STG TO LL_WRITER;
"""

out = HERE / "init"
out.mkdir(exist_ok=True)
(out / "01_schema.sql").write_text(schema)
(out / "02_data.sql").write_text(data)
(out / "03_reader.sql").write_text(reader)
(out / "04_staging.sql").write_text(staging)
print(f"{len(cust_ids)} customers, {len(orders)} orders, {shp - 70001} shipments, {inv} invoices -> {out}")
