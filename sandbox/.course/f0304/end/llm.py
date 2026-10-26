"""Talk to Claude: one function for every call."""
import json

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic()
MODEL = "claude-sonnet-5-5"


def ask(prompt, schema=None):
    """Send one prompt. Return the text, or a dict that fits the schema."""
    config = {"effort": "low"}
    if schema:
        config["format"] = {"type": "json_schema", "schema": schema}
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        output_config=config,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[-1].text
    if schema:
        return json.loads(text)
    return text
