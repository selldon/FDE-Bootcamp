"""Look at Ledgerline before we use it: tables, columns, codes."""
from ledgerline import connection

cursor = connection.cursor()
cursor.execute("""SELECT table_name, COUNT(*) FROM all_tab_columns
WHERE owner = 'LEDGERLINE' GROUP BY table_name ORDER BY table_name""")
for table, columns in cursor:
    print(table, columns, "columns")

cursor.execute("""SELECT column_name, data_type FROM all_tab_columns
WHERE owner = 'LEDGERLINE' AND table_name = 'LL_ORD_HDR'
ORDER BY column_id""")
for column, kind in cursor:
    print("  LL_ORD_HDR", column, kind)

cursor.execute("""SELECT ord_stat_cd, COUNT(*) FROM ledgerline.ll_ord_hdr
GROUP BY ord_stat_cd ORDER BY ord_stat_cd""")
for code, orders in cursor:
    print("status", code, orders, "orders")
