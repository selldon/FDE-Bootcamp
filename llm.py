"""Talk to Claude: one function for every call."""
import json

from anthropic import Anthropic
from dotenv import load_dotenv

import traces

load_dotenv()
client = Anthropic()
MODEL = "claude-sonnet-5-5"
# US dollars per million tokens (input, output), per model, from Anthropic's pricing page.
# A model missing here is stored with no cost, never with a guessed one.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0)}


def cost(model, usage):
    """The cost of one call from its tokens, or None for a model with no price."""
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    return (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000


def ask(prompt, schema=None, model=MODEL, usage=None):
    """Send one prompt. Return the text, or a dict that fits the schema."""
    config = {"effort": "low"}
    if schema:
        config["format"] = {"type": "json_schema", "schema": schema}
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        output_config=config,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        traces.record("ask", model, prompt, f"refusal: {response.stop_details.category}",
                      response.usage, cost(model, response.usage))
        raise ValueError(response.stop_details.category)
    if usage is not None:
        usage.append(response.usage)
    text = response.content[-1].text
    traces.record("ask", model, prompt, text, response.usage, cost(model, response.usage))
    if schema:
        return json.loads(text)
    return text


def chat(system, tools, messages, usage=None):
    """One turn of the tool-using conversation. Return the response."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        output_config={"effort": "low"},
        system=system,
        tools=tools,
        messages=messages,
    )
    if usage is not None:
        usage.append(response.usage)
    traces.record("chat", MODEL, {"system": system, "messages": messages}, response.content,
                  response.usage, cost(MODEL, response.usage))
    return response
