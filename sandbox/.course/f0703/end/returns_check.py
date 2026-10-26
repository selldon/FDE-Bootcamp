"""Thirty borderline returns, three runs: how often is the answer right?"""
import json
from concurrent.futures import ThreadPoolExecutor

from returns_prompt import decide

with open("data/borderline_returns.json") as f:
    cases = json.load(f)


def run(decider):
    """One answer for every case, thirty at a time."""
    facts = []
    for case in cases:
        facts.append(case["facts"])
    with ThreadPoolExecutor(30) as pool:
        return list(pool.map(decider, facts))


def measure(name, decider):
    """Three runs of all thirty cases: the misses, then the score."""
    for number in [1, 2, 3]:
        right = 0
        for case, answer in zip(cases, run(decider)):
            if answer == case["right"]:
                right += 1
            else:
                print("  ", case["id"], case["facts"], "said", answer)
        print(name, "run", number, ":", right, "of 30 right")


measure("prompt", decide)
