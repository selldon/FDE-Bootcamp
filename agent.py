"""The agent loop: Claude asks for tools, our code runs them."""
import json

from llm import MODEL, client
from tools import TOOLS, delivery_status, find_order

SYSTEM = """You are the DemoStore support assistant.
Answer questions about orders with the tools, in two or three
short sentences. Never guess a date or a status. If a tool says
the customer is not verified, ask them to enter the one-time
code from their email first."""


def run_tool(name, args, customer):
    """Run the tool Claude asked for, for our customer."""
    if name == "find_order":
        return find_order(args["number"], customer)
    return delivery_status(args["tracking"])


def answer(message, customer, usage=None):
    """Loop until Claude stops asking for tools."""
    messages = [{"role": "user", "content": message}]
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            output_config={"effort": "low"},
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        if usage is not None:
            usage.append(response.usage)
        if response.stop_reason != "tool_use":
            return response.content[-1].text
        messages.append({"role": "assistant",
                         "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                result = run_tool(block.name, block.input,
                                  customer)
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result)})
        messages.append({"role": "user", "content": results})
