"""Find the chunks that fit a question, for one market and one day."""
from datetime import date, timedelta

from index_policies import db, model

ALLOWED = """market IN (%(market)s, 'ALL')
    AND valid_from <= %(day)s
    AND (valid_to IS NULL OR valid_to >= %(day)s)"""


def search(question, market, day):
    """The best chunks for this customer's market, valid on this day."""
    vector = list(model.query_embed(question))[0]
    words = " or ".join(question.split())
    values = {"market": market, "day": day, "vector": vector, "words": words}
    by_meaning = db.execute(
        "SELECT title, section, body, url FROM chunks WHERE " + ALLOWED
        + " ORDER BY embedding <=> %(vector)s LIMIT 3",
        values,
    ).fetchall()
    by_words = db.execute(
        "SELECT title, section, body, url FROM chunks WHERE " + ALLOWED
        + " AND words @@ websearch_to_tsquery('english', %(words)s)"
        + " ORDER BY ts_rank(words, websearch_to_tsquery('english', %(words)s))"
        + " DESC LIMIT 2",
        values,
    ).fetchall()
    found = by_meaning
    for row in by_words:
        if row not in found:
            found.append(row)
    return found


if __name__ == "__main__":
    question = "Is delivery free on a 40 pound order?"
    for row in search(question, "UK", date.today()):
        print("today:", row[0], "-", row[1])
    later = date.today() + timedelta(days=10)
    for row in search(question, "UK", later):
        print("in ten days:", row[0], "-", row[1])
