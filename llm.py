"""Talk to Claude: one function for every call."""
import json

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic()
MODEL = "claude-sonnet-5-5"


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
        raise ValueError(response.stop_details.category)
    if usage is not None:
        usage.append(response.usage)
    text = response.content[-1].text
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
    return response
