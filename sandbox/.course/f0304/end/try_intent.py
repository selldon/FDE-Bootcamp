from intent import classify

MESSAGES = [
    "Hi, where is my order DS-20417? It was due on Monday.",
    "I want to return the laptop from order DS-20388. It is too loud.",
    "Third time I am writing. I want a real person, now!",
]

for message in MESSAGES:
    result = classify(message)
    print(result["intent"], result["order_number"], result["needs_human"])
