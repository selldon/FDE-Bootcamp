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
