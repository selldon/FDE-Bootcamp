"""Three models on the labeled conversations, three runs each."""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from intent import classify

MODELS = ["claude-opus-5-5", "claude-sonnet-5-5",
          "claude-haiku-5-5"]
PRICES = {  # dollars per million tokens: input, output
    "claude-opus-5-5": (4, 20),
    "claude-sonnet-5-5": (2, 10),
    "claude-haiku-5-5": (0.10, 0.50),
}

with open("data/conversations.json") as f:
    chats = json.load(f)


def check(chat, model):
    """Classify one conversation; compare with its labels."""
    usage = []
    start = time.time()
    answer = classify(chat["message"], model, usage)
    seconds = time.time() - start
    person = answer["needs_human"]
    price_in, price_out = PRICES[model]
    cost = (usage[0].input_tokens * price_in
            + usage[0].output_tokens * price_out) / 1_000_000
    return {
        "right": answer["intent"] == chat["intent"],
        "missed": chat["needs_human"] and not person,
        "extra": person and not chat["needs_human"],
        "cost": cost,
        "seconds": seconds,
    }


def run(model):
    """Check all forty conversations, twenty at a time."""
    with ThreadPoolExecutor(20) as pool:
        return list(pool.map(check, chats, [model] * len(chats)))


for model in MODELS:
    rights = []
    missed = extra = cost = seconds = 0
    for attempt in [1, 2, 3]:
        right = 0
        for result in run(model):
            right += result["right"]
            missed += result["missed"]
            extra += result["extra"]
            cost += result["cost"]
            seconds += result["seconds"]
        rights.append(right)
    calls = 3 * len(chats)
    print(model)
    print("  right of 40:", rights, " missed:", missed,
          " extra:", extra)
    print("  $ per 1000:", round(cost / calls * 1000, 2),
          " seconds:", round(seconds / calls, 1))
