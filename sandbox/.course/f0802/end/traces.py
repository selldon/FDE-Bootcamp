"""Every call to Claude, kept in our own database."""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
TABLE = """CREATE TABLE IF NOT EXISTS traces (
  id serial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  conversation text,
  model text NOT NULL,
  sent text NOT NULL,
  answer text NOT NULL,
  input_tokens integer NOT NULL,
  output_tokens integer NOT NULL,
  cost numeric(10, 6) NOT NULL,
  ms integer NOT NULL)"""
ADD = """INSERT INTO traces (conversation, model, sent, answer,
  input_tokens, output_tokens, cost, ms)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""

db = psycopg.connect(os.environ["OURDB_URL"], autocommit=True)
db.execute(TABLE)


def record(conversation, model, sent, answer, usage, cost, ms):
    """One row per call: what went in, what came back, the cost."""
    db.execute(ADD, (conversation, model, sent, answer,
                     usage.input_tokens, usage.output_tokens,
                     cost, ms))
