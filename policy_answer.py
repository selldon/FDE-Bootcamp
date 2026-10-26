"""The `policy_answer` tool (B18, IT21): sections of the customer's market valid today, found by meaning and by words.

The market never comes from the model alone (`market_for`): a verified customer's market wins, then the one the API
sent, then one the customer named in the chat. With none, the tool says so and the assistant asks - it never guesses.
A section counts only if the question is close enough in meaning (`MIN_SIMILARITY`); with nothing close the result is
`no_page` and the assistant offers a person. Order of the sections: meaning rank and words rank, fused (RRF).
"""
import re

import psycopg

import embedder as real_embedder
import policy_index
import returns
import tools

MARKETS = frozenset(returns.WINDOWS)
# Cosine similarity of bge-small below which a section does not answer the question. Calibrated on the 8 policy conversations
# (Phase 10): questions the pages do not answer score up to 0.70, those they do answer from 0.72. Thin on both sides.
MIN_SIMILARITY = 0.71
LIMIT = 3
RRF_K = 60
NO_PAGE = {"no_page": True}
ASK_MARKET = {"error": "market unknown",
              "instruction": "Ask the customer which country they are in (UK, DE, FR, IT or US). Do not guess."}
UNAVAILABLE = {"error": "policy pages unavailable"}

_index = None
_embedder = None


def get_index():
    """The policy index the tool reads; the real one unless a test or the replay set another."""
    global _index
    if _index is None:
        _index = policy_index.Index()
    return _index


def set_systems(index=None, embedder=None):
    global _index, _embedder
    _index, _embedder = index, embedder


def _embed(texts):
    return (_embedder.embed if _embedder else real_embedder.embed)(texts)


def normalize_market(value):
    """A market code we know, or None."""
    code = value.strip().upper() if isinstance(value, str) else ""
    return code if code in MARKETS else None


def market_for(verified_market, api_market, said_market):
    """verified customer > the API's market > the one named in the chat; None if none is known."""
    for candidate in (verified_market, api_market, said_market):
        market = normalize_market(candidate)
        if market:
            return market
    return None


def _words(question):
    return sorted({w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) >= 3})


def policy_answer(question, market, today=None):
    """The top sections for this question, or `no_page`. `market` must be a known market (see `market_for`)."""
    market = normalize_market(market)
    if market is None:
        return dict(ASK_MARKET)
    today = today or tools.clock().date()
    try:
        [vector] = _embed([question])
        found = get_index().search(vector, _words(question), market, today)
    except (psycopg.Error, OSError, RuntimeError):
        return dict(UNAVAILABLE)
    latest = {}  # two versions valid together: the later valid-from (then the later version) is the rule
    for row in found:
        key = (row["page_id"], row["heading"])
        best = latest.get(key)
        if best is None or (row["valid_from"], row["version"]) > (best["valid_from"], best["version"]):
            latest[key] = row
    rows = list(latest.values())
    by_meaning = sorted(rows, key=lambda r: (-r["similarity"], r["page_id"], r["heading"]))
    by_words = sorted((r for r in rows if r["word_score"] > 0), key=lambda r: (-r["word_score"], r["page_id"], r["heading"]))
    score = {id(r): 1 / (RRF_K + n) for n, r in enumerate(by_meaning, 1)}
    for n, r in enumerate(by_words, 1):
        score[id(r)] += 1 / (RRF_K + n)
    close = [r for r in rows if r["similarity"] >= MIN_SIMILARITY]
    top = sorted(close, key=lambda r: (-score[id(r)], r["page_id"], r["heading"]))[:LIMIT]
    if not top:
        return dict(NO_PAGE)
    return {"market": market,
            "sections": [{"heading": r["heading"], "text": r["text"], "link": r["link"]} for r in top]}
