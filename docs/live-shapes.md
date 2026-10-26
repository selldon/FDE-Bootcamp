# What the real systems look like

Found by `probe_live.py` (read-only) on 2026-10-23. Emails are not copied here.

## Ledgerline (Oracle copy, read-only account, schema `LEDGERLINE`)

| Table | Rows | Columns we need | Maps to |
|---|---|---|---|
| `LL_CUST` | 33 | `CUST_ID`, `EMAIL_ADDR`, `CUST_NM`, `MKT_CD` (`CUST_TYP_CD`, `CRT_DT` not needed) | the order's customer (email, lower case) and market |
| `LL_ORD_HDR` | 33 | `ORD_NO`, `CUST_ID`, `ORD_STAT_CD` (CHAR), `PROM_DT` (DATE) (`ORD_DT`, `CURR_CD`, `ORD_TOT` not needed) | order number, owner, status, promised date |
| `LL_ORD_LN` | 37 | `ORD_NO`, `LN_NO`, `ITEM_DESC` | items (the description, not the SKU) |
| `LL_SHPMT` | 35 | `ORD_NO`, `LN_NO`, `TRK_NO`, `CARR_CD`, `SHIP_DT` | parcels of an order |
| `LL_INV_HDR` | 31 | - | not read in this build (invoices, money) |

- Status codes in the copy: `D` 21, `F` 9, `N` 2, `S` 1. No `X` yet, but the mapping table keeps it. These are the same
  counts as the fake `data/orders.json` (delivered 21, shipped 9, processing 2, partly shipped 1): the copy and the fake
  describe the same 33 orders. In the fake, `N` is called "processing"; the spec calls it "new".
- Every order has a customer in `LL_CUST` (0 orphans). Customers are joined by `CUST_ID`; the email is in `LL_CUST`.

## Carrier SFTP server (`upload/`, not the root)

- Files: `upload/carrier-YYYY-MM-DD.csv`, one per night (20, 21 and 22 Oct present). 33 rows each.
- Encoding is **cp1252, not UTF-8** (two lines of the newest file have non-ASCII characters).
- The columns **change between files**: the 20th and 21st have `tracking,status,place,date`; the 22nd has
  `tracking,status,pickup_point,place,date` (new column, mostly empty, quoted values with commas like
  `"Locker 4, Leeds Station"`). The parser must read by header name, with the csv module.
- Statuses seen: `delivered`, `in transit`, `out for delivery` (new in the 22nd file).
- `date` is a date only, with no time of day.

## Our PostgreSQL

Connects; no tables yet.

## Differences from the fakes, and what they change in the plan

1. **No "changed since" column in Ledgerline.** No table has an update or modification time (`ORD_DT` is the order date and
   does not move when the status does). IT11 ("loads only what changed since the last successful run") cannot be a
   timestamp query. Options: (a) read all orders each run - 33 rows today, and the upsert makes it safe (IT12) - and the
   watermark is the time of the last successful run, kept for the checks; (b) compare a hash of each row with the store
   and write only the rows that differ. Needs your decision before Phase 2.
2. **Duplicate tracking numbers.** `LL_SHPMT` has 35 rows but 33 distinct tracking numbers: one parcel can carry two order
   lines. The order store key is the tracking number (IT12), so the pipeline must collapse them; an order keeps all its parcels.
3. **The carrier's news has a date but no time.** The 30-hour rule (B9, IT14) needs a rule for "how old": measured from the
   end of the news date, or from the file's own time (`mtime` on the server, or the date in its name). Needs your decision
   before Phase 7.
4. **Header order and encoding vary** (see above): Phase 3 reads by header name and decodes cp1252.
5. The carrier's status words are the carrier's own; they are not mapped to the order status (the order status comes from Ledgerline).

## Build 3: what a return needs (found by `python probe_live.py build3`, read-only, 2026-10-23)

Names, types and counts only; no rows, no emails.

### Ledgerline (reader account)

| Need | Where | Note |
|---|---|---|
| Price per unit | `LL_ORD_LN.UNIT_PRC` NUMBER(10,2) | |
| Tax of the line | `LL_ORD_LN.TAX_AMT` NUMBER(10,2) | Looks like the tax of the whole line (all units), to confirm against `ORD_TOT`. |
| Quantity | `LL_ORD_LN.QTY` NUMBER(5,0) | "Split by item" (IT17) means by unit. |
| Currency | `LL_ORD_HDR.CURR_CD`: EUR 18, USD 8, GBP 7 | On the order, not the line. |
| Order total | `LL_ORD_HDR.ORD_TOT` NUMBER(12,2) | The sum the refunds must add up to (B14). |
| Market | `LL_CUST.MKT_CD`: US 8, UK 7, DE 7, IT 6, FR 5 | All five are in the borderline cases. |
| Customer type | `LL_CUST.CUST_TYP_CD`: `C` 32, `B` 1 | `B` is presumably DemoStore Business; one customer only. |
| Product kind | **no column** | Only `SKU_CD` (for example `AER-14-LAP`, `WEB-W1`) and the free text `ITEM_DESC`. The rule needs "earbuds" and "software" (IT15). |
| Delivery date of a line | `LL_SHPMT.LN_NO` links a parcel to a line; the date is the carrier's news date in our store | Ledgerline has `SHIP_DT` (shipped), not delivered. |
| Holding table `LL_RTN_REQ_STG` | **not visible to the reader** | Listed once through `LL_WRITER` on 2026-10-23, with a query that returns no rows (nothing inserted): `REQ_ID` NUMBER(10) not null, `ORD_NO` VARCHAR2(12) not null, `LN_NO` NUMBER(3) not null, `RFND_AMT` NUMBER(10,2) not null, `REQ_KEY` VARCHAR2(64) null, `STG_STAT_CD` CHAR(1) not null, `CRT_TS` TIMESTAMP(6) not null. Unique key, `REQ_ID` source and the status letters unknown (OQ-S3-3). |

### ServiceNow (`SERVICENOW_URL` in `.env`, account `fde_tasks`)

- Reachable. `GET /api/now/table/sc_task` answers 200 with an empty `result` (0 rows), so the probe sees no field names.
- `GET /api/now/table/interaction` answers **401 `User Not Authenticated`** with the same account that reads `sc_task`.
- `sys_dictionary`, `incident` and the table list answer 404: this is not a full ServiceNow, only some tables are served.
- The URL in `.env` has port 8021; `.env.example` says 8020. The code reads `.env`, so nothing to change; noted in case the example is wrong.
- No count header (`X-Total-Count`) is sent.

### Differences from what Phases 2-8 assume

1. **Product kind is not in Ledgerline.** Decided (D1 in `docs/spec-3.md`): a mapping of `SKU_CD` in code; an unknown SKU goes to a person.
2. **Columns of `LL_RTN_REQ_STG`:** found (above). There is no customer, currency or reason column.
3. **`interaction`:** `fde_tasks` may create rows (`short_description`, `u_conversation`) but not read them; the 401 was the read (D3).
4. **`sc_task`:** `fde_tasks` creates and reads it with `short_description` and `u_draft` (D3).

## Build 4: what the policy index needs (found by `python probe_live.py build4`, read-only, 2026-10-26)

### Confluence (`CONFLUENCE_URL` in `.env`)

- Reachable with **no login** (plain GET). A mock, not a full Confluence: `/rest/api/user/current`, `/rest/api/space/POL` and `/rest/api/space` answer 404.
  Only `GET /rest/api/content?spaceKey=POL&type=page&limit=100` works: `{"results": [...], "size": 16}`, all 16 pages in one answer.
- A page: `id` (text), `type`, `title`, `version` `{number, when}`, `metadata` `{market, valid_from, valid_to}`, `_links.webui` (a path, for example
  `/wiki/spaces/POL/pages/1001`), and `body` as a **Markdown string** (not `body.storage.value`). Market and the valid dates are in `metadata`, not in labels.
- Pages: Returns, Warranty and Delivery for each of UK, DE, FR, IT, US (15 pages), plus `1016` "Delivery - UK (new rule)" valid from 2026-11-02;
  `1003` "Delivery - UK" is valid until 2026-11-01. `valid_to` is null for the rest. No page has a holiday rule, payment methods, shipping countries or a buy-back.
- Sections are `##` headings. Returns: Return window, Condition, Refunds, Company customers. Warranty: What the warranty covers, What it does not cover, How to claim.
  Delivery: Delivery costs, Delivery times. 4 + 3 + 2 sections.
- All pages, also those of DE, FR and IT, are written in **English**, so the English-only embedder (D1) fits.
- No version history through the API (only the current version); two versions of one rule appear as two pages with different valid dates (1003 and 1016).
- The "Return window" sections say 14 days (UK, DE, FR, IT) and 30 / 15 opened (US): equal to `returns.WINDOWS` / `US_OPENED` today.

### Our PostgreSQL

- PostgreSQL 16.10. Extension `vector` 0.8.0 is **available, not installed**; `pg_trgm` is available too. Tables now: `orders`, `parcels`, `load_state`.
  `CREATE EXTENSION vector` is a change to the container's database: Phase 6 does it only after you say yes (it is not done by the probe).

### Differences from what Phases 5-9 assume

1. The page body is Markdown, so `policy.py` cuts on `## ` headings (not HTML). `confluence.py` reads one list call; there is no per-page call and no version history.
2. Market and valid dates are in `metadata` (always present on the 16 pages); a page without them is still an error naming the page.
3. Two rules for the same thing are two pages with different dates, so the "versions" of Phase 6 are really page ids; both stay in the index and "valid today" decides.
4. The key for G4 has 5 of 8 conversations with no page (`data/policy_key.json`): the "offer a person" path is half of the check.
