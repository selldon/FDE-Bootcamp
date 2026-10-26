"""Talk to Claude: one function for every call."""
import json
import os
import time

from anthropic import Anthropic, APIConnectionError, APIStatusError
from dotenv import load_dotenv

from traces import record

load_dotenv()
client = Anthropic(timeout=15.0, max_retries=2)
MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-5-5")
PRICES = {  # dollars per million tokens: input, output
    "claude-opus-5-5": (4, 20),
    "claude-sonnet-5-5": (2, 10),
    "claude-haiku-5-5": (0.10, 0.50),
}


class NoAnswer(Exception):
    """Claude did not answer: no connection, too slow, or too busy."""


def call(conversation, **request):
    """Every request to Claude goes through here and leaves a trace."""
    start = time.time()
    try:
        response = client.messages.create(**request)
    except APIConnectionError:
        raise NoAnswer("no connection, or too slow")
    except APIStatusError as error:
        if error.status_code == 429 or error.status_code >= 500:
            raise NoAnswer(f"Claude answered {error.status_code}")
        raise
    ms = round((time.time() - start) * 1000)
    price_in, price_out = PRICES[request["model"]]
    cost = (response.usage.input_tokens * price_in
            + response.usage.output_tokens * price_out) / 1_000_000
    sent = str(request["messages"][-1]["content"])
    reply = []
    for block in response.content:
        if block.type == "text":
            reply.append(block.text)
        if block.type == "tool_use":
            reply.append(f"{block.name} {block.input}")
    record(conversation, request["model"], sent, " | ".join(reply),
           response.usage, cost, ms)
    return response


def ask(prompt, schema=None, model=MODEL, usage=None,
        conversation=None):
    """Send one prompt. Return the text, or a dict that fits the schema."""
    config = {"effort": "low"}
    if schema:
        config["format"] = {"type": "json_schema", "schema": schema}
    response = call(
        conversation,
        model=model,
        max_tokens=1000,
        output_config=config,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise ValueError(response.stop_details.category)
    if usage is not None:
        usage.append(response.usage)
    text = response.content[-1].text
    if schema:
        return json.loads(text)
    return text
