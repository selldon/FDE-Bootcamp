"""The policy index in our PostgreSQL (IT21, IT22): every section of every `POL` page with its embedding and its words.

`rebuild()` reads the pages, cuts them (`policy`), embeds the sections and replaces the index in one transaction: a
section is stored by (page id, version, heading); sections of pages or versions no longer returned are removed.
Everything that can fail (Confluence, a bad page, the embedder) happens before the transaction, so a failure leaves the old
index. Two versions of one page are two sets of rows - which one counts is decided by the dates ("valid today"), not here.
Run `python policy_index.py` hourly, like `pipeline.py` (no lock yet - see docs/quick-fixes.md). `FakeIndex` has the same interface.
`check_windows` (IT22) compares `returns.WINDOWS` / `US_OPENED` with the "Return window" sections valid today; the job
stores the index first, then exits non-zero on a difference. `python policy_index.py --check` runs only the check.
"""
import re
import sys

import psycopg
from psycopg import sql

import config
import confluence
import embedder as real_embedder
import policy
import returns
import tools

KEY = ("page_id", "version", "heading")
FIELDS = KEY + ("text", "market", "valid_from", "valid_to", "link", "embedding")


def tables(name="policy_sections", dimensions=real_embedder.DIMENSIONS):
    """The CREATE statements. `CREATE EXTENSION vector` is a change to our own database; the author said yes (plan-4)."""
    t = sql.Identifier(name)
    return [
        sql.SQL("CREATE EXTENSION IF NOT EXISTS vector"),
        sql.SQL("""CREATE TABLE IF NOT EXISTS {t} (
            page_id text NOT NULL, version integer NOT NULL, heading text NOT NULL, text text NOT NULL,
            market text NOT NULL, valid_from date NOT NULL, valid_to date, link text,
            embedding vector({d}) NOT NULL,
            words tsvector GENERATED ALWAYS AS (to_tsvector('english', heading || ' ' || text)) STORED,
            PRIMARY KEY (page_id, version, heading))""").format(t=t, d=sql.SQL(str(int(dimensions)))),
        sql.SQL("CREATE INDEX IF NOT EXISTS {i} ON {t} USING gin (words)")
        .format(i=sql.Identifier(name + "_words"), t=t),
    ]


def _literal(vector):
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class Index:
    """The real table."""

    def __init__(self, url=None, name="policy_sections", **connect_args):
        self.url = url or config.store_url()
        self.name = name
        self.table = sql.Identifier(name)
        self.connect_args = connect_args

    def _connect(self):
        return psycopg.connect(self.url, **self.connect_args)

    def create_tables(self):
        with self._connect() as conn:
            for statement in tables(self.name):
                conn.execute(statement)

    def replace(self, rows):
        """Upsert `rows` and remove every other section, in one transaction (any error rolls it all back)."""
        upsert = sql.SQL("""INSERT INTO {t} (page_id, version, heading, text, market, valid_from, valid_to, link, embedding)
            VALUES (%(page_id)s, %(version)s, %(heading)s, %(text)s, %(market)s, %(valid_from)s, %(valid_to)s,
                    %(link)s, %(embedding)s::vector)
            ON CONFLICT (page_id, version, heading) DO UPDATE SET text = EXCLUDED.text, market = EXCLUDED.market,
                valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to, link = EXCLUDED.link,
                embedding = EXCLUDED.embedding""").format(t=self.table)
        with self._connect() as conn:
            for row in rows:
                conn.execute(upsert, {**row, "embedding": _literal(row["embedding"])})
            wanted = {tuple(row[k] for k in KEY) for row in rows}
            have = conn.execute(sql.SQL("SELECT page_id, version, heading FROM {t}").format(t=self.table)).fetchall()
            for key in set(have) - wanted:
                conn.execute(sql.SQL("DELETE FROM {t} WHERE page_id = %s AND version = %s AND heading = %s")
                             .format(t=self.table), key)

    def counts_by_market(self):
        with self._connect() as conn:
            return dict(conn.execute(sql.SQL("SELECT market, count(*) FROM {t} GROUP BY market ORDER BY market")
                                     .format(t=self.table)).fetchall())

    def all(self):
        with self._connect() as conn:
            conn.row_factory = psycopg.rows.dict_row
            rows = conn.execute(sql.SQL("SELECT page_id, version, heading, text, market, valid_from, valid_to, link "
                                        "FROM {t} ORDER BY page_id, version, heading").format(t=self.table)).fetchall()
        return rows


    def search(self, vector, words, market, today):
        """Every section of this market valid on `today`, with its meaning score (cosine, 0..1) and words score."""
        query = " | ".join(words) if words else None
        with self._connect() as conn:
            conn.row_factory = psycopg.rows.dict_row
            return conn.execute(sql.SQL("""SELECT page_id, version, heading, text, link, valid_from,
                    1 - (embedding <=> %(v)s::vector) AS similarity,
                    CASE WHEN %(q)s::text IS NULL THEN 0 ELSE ts_rank(words, to_tsquery('english', %(q)s)) END AS word_score
                FROM {t} WHERE market = %(m)s AND valid_from <= %(d)s AND (valid_to IS NULL OR valid_to >= %(d)s)""")
                                .format(t=self.table), {"v": _literal(vector), "q": query, "m": market, "d": today}).fetchall()


class FakeIndex:
    """The same interface in memory. `replace` is all-or-nothing, like the transaction."""

    def __init__(self):
        self.rows = {}
        self.fail_after = None  # raise after this many rows, as a broken connection would

    def replace(self, rows):
        new = {}
        for n, row in enumerate(rows):
            if self.fail_after is not None and n >= self.fail_after:
                raise RuntimeError("connection lost")
            new[tuple(row[k] for k in KEY)] = dict(row)
        self.rows = new

    def search(self, vector, words, market, today):
        found = []
        for row in self.rows.values():
            if not valid(row, market, today):
                continue
            body = set(re.findall(r"[a-z0-9]+", f"{row['heading']} {row['text']}".lower()))
            found.append({**{k: v for k, v in row.items() if k not in ("embedding", "market", "valid_to")},
                          "similarity": _cosine(vector, row["embedding"]),
                          "word_score": float(len(body & set(words)))})
        return found

    def counts_by_market(self):
        counts = {}
        for row in self.rows.values():
            counts[row["market"]] = counts.get(row["market"], 0) + 1
        return dict(sorted(counts.items()))

    def all(self):
        return [{k: v for k, v in self.rows[key].items() if k != "embedding"} for key in sorted(self.rows)]


def valid(row, market, today):
    """The rule of "valid today": the section's market, and today inside its dates (the last day counts)."""
    return (row["market"] == market and row["valid_from"] <= today
            and (row["valid_to"] is None or row["valid_to"] >= today))


def _cosine(a, b):
    na, nb = sum(x * x for x in a) ** 0.5, sum(x * x for x in b) ** 0.5
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb) if na and nb else 0.0


def rebuild(source=None, embedder=None, index=None):
    """Read, cut, embed, then replace the index. Returns the number of sections stored."""
    source = source or confluence
    embed = embedder.embed if embedder else real_embedder.embed
    index = index or Index()
    cuts = policy.all_sections(source.pages())
    seen = set()
    for cut in cuts:
        key = tuple(cut[k] for k in KEY)
        if key in seen:
            raise policy.PolicyError(f"page {cut['page_id']} has the heading {cut['heading']!r} twice")
        seen.add(key)
    vectors = embed([f"{c['heading']}\n{c['text']}" for c in cuts]) if cuts else []
    index.replace([{**cut, "embedding": vector} for cut, vector in zip(cuts, vectors, strict=True)])
    return len(cuts)


_DAYS = re.compile(r"(\d+)\s*(?:calendar\s+|working\s+)?days?", re.IGNORECASE)
_OPENED = (re.compile(r"(\d+)\s*(?:days?\s*)?(?:if |when |for )?(?:the item is |it is )?opened\b", re.IGNORECASE),
           re.compile(r"\bopened\b[^.\d]*(\d+)", re.IGNORECASE))


def _page_windows(text):
    """(days, days if opened) stated in a "Return window" text; None for what it does not state."""
    opened = None
    for pattern in _OPENED:
        found = pattern.search(text)
        if found:
            opened = int(found.group(1))
            text = text[:found.start()] + text[found.end():]
            break
    found = _DAYS.search(text)
    return (int(found.group(1)) if found else None), opened


def check_windows(index, today):
    """Differences between the code's windows and the pages valid `today`: a list of messages, empty when equal."""
    sections = [r for r in index.all() if r["heading"].strip().lower() == "return window"]
    problems = []
    for market, code_days in returns.WINDOWS.items():
        valid_now = [r for r in sections if valid(r, market, today)]
        if not valid_now:
            problems.append(f"{market}: no 'Return window' section valid on {today}; code says {code_days} days")
        for row in valid_now:
            days, opened = _page_windows(row["text"])
            where = f"page {row['page_id']} version {row['version']}"
            if days is None:
                problems.append(f"{market}: {where} states no window; code says {code_days} days")
            elif days != code_days:
                problems.append(f"{market}: code says {code_days} days, {where} says {days} days")
            if market == "US":
                if opened is None:
                    problems.append(f"US: {where} states no window for opened items; code says {returns.US_OPENED} days")
                elif opened != returns.US_OPENED:
                    problems.append(f"US: code says {returns.US_OPENED} days if opened, {where} says {opened} days")
    return problems


def report_windows(index, today=None):
    problems = check_windows(index, today or tools.clock().date())
    for problem in problems:
        print(f"RETURN WINDOW DIFFERS - {problem}", file=sys.stderr)
    if not problems:
        print("return windows: code and pages agree")
    return 1 if problems else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        index = Index()
        if "--check" in argv:
            return report_windows(index)
        index.create_tables()
        before = index.counts_by_market()
        stored = rebuild(index=index)
    except (confluence.ConfluenceError, policy.PolicyError, psycopg.Error, OSError, RuntimeError) as error:
        print(f"policy index not rebuilt: {error}", file=sys.stderr)
        return 1
    print(f"{stored} sections stored; per market before {before}, after {index.counts_by_market()}")
    return report_windows(index)


if __name__ == "__main__":
    sys.exit(main())
