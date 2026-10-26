"""One connection to Ledgerline, read only, for every script."""
import os

import oracledb
from dotenv import load_dotenv

load_dotenv()
connection = oracledb.connect(
    user=os.environ["LEDGERLINE_USER"],
    password=os.environ["LEDGERLINE_PASSWORD"],
    dsn=os.environ["LEDGERLINE_DSN"],
)
