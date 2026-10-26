"""Copy DemoStore's policies and product descriptions into our database."""
import json
import os

import httpx
import psycopg
from dotenv import load_dotenv
from fastembed import TextEmbedding
from pgvector.psycopg import register_vector

load_dotenv()
CONFLUENCE = os.environ["CONFLUENCE_URL"]
model = TextEmbedding("BAAI/bge-small-en-v1.5")
db = psycopg.connect(os.environ["OURDB_URL"])
register_vector(db)

TABLE = """CREATE TABLE IF NOT EXISTS chunks (
    page TEXT, version INT, title TEXT, section TEXT, body TEXT,
    market TEXT, valid_from DATE, valid_to DATE, url TEXT,
    embedding VECTOR(384),
    words TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', body)) STORED)"""


def policy_pages():
    """Every page of the policy space, with its text and its labels."""
    params = {"spaceKey": "POL", "expand": "body,version,metadata"}
    reply = httpx.get(CONFLUENCE + "/rest/api/content", params=params)
    return reply.json()["results"]


def add(page, version, title, section, body, market, start, end, url):
    """One chunk: its text, its labels and its embedding."""
    vector = list(model.passage_embed(title + ". " + section + ": " + body))[0]
    db.execute(
        "INSERT INTO chunks VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (page, version, title, section, body, market, start, end, url, vector),
    )


def index():
    """Build the table of chunks again, from the sources."""
    db.execute(TABLE)
    db.execute("DELETE FROM chunks")
    for page in policy_pages():
        labels = page["metadata"]
        url = CONFLUENCE + page["_links"]["webui"]
        for part in page["body"].split("## ")[1:]:
            section, body = part.split("\n", 1)
            add(page["id"], page["version"]["number"], page["title"], section,
                body.strip(), labels["market"], labels["valid_from"],
                labels["valid_to"], url)
    with open("data/catalog.json") as f:
        catalog = json.load(f)
    for product in catalog["products"]:
        add("atlas", None, product["name"], "Description",
            product["description"], "ALL", catalog["exported"], None, None)
    db.commit()


def stale_pages():
    """Pages that changed in Confluence after our last index."""
    indexed = {}
    for page, version in db.execute("SELECT DISTINCT page, version FROM chunks"):
        indexed[page] = version
    stale = []
    for page in policy_pages():
        if indexed.get(page["id"]) != page["version"]["number"]:
            stale.append(page["title"])
    return stale


if __name__ == "__main__":
    index()
    count = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(count, "chunks in our database")
