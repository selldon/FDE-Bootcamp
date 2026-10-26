"""One question while Claude is too busy: a stand-in answers 429."""
import os

os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:8050"
os.environ["ANTHROPIC_API_KEY"] = "test"
os.environ["ANTHROPIC_LOG"] = "info"

from llm import ask

print(ask("Where is my order DS-20417?"))
