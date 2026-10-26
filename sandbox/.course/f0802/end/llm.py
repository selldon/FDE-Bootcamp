"""Talk to Claude: one function for every call."""
import json
import time

from anthropic import Anthropic
from dotenv import load_dotenv

from traces import record

load_dotenv()
client = Anthropic()
MODEL = "claude-sonnet-5-5"
PRICES = {  # dollars per million tokens: input, output
    "claude-opus-5-5": (4, 20),
    "claude-sonnet-5-5": (2, 10),
    "claude-haiku-5-5": (0.10, 0.50),
}


def ask(prompt, schema=None, model=MODEL, usage=None,
        conversation=None):
    """Send one prompt. Return the text, or a dict that fits the schema."""
    config = {"effort": "low"}
    if schema:
        config["format"] = {"type": "json_schema", "schema": schema}
    start = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        output_config=config,
        messages=[{"role": "user", "content": prompt}],
    )
    ms = round((time.time() - start) * 1000)
    if response.stop_reason == "refusal":
        raise ValueError(response.stop_details.category)
    if usage is not None:
        usage.append(response.usage)
    text = response.content[-1].text
    price_in, price_out = PRICES[model]
    cost = (response.usage.input_tokens * price_in
            + response.usage.output_tokens * price_out) / 1_000_000
    record(conversation, model, prompt, text, response.usage, cost, ms)
    if schema:
        return json.loads(text)
    return text
