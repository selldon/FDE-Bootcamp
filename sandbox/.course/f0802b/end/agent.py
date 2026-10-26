"""The agent loop: Claude asks for tools, our code runs them."""
import json

from llm import MODEL, call
from prices import price
from tools import TOOLS, delivery_status, find_order
from verify import send_code

SYSTEM = """You are the DemoStore support assistant.
Answer questions about orders with the tools, in two or three
short sentences. Never guess a date or a status. If a tool says
the customer is not verified, call send_code with their order
number (ask for it if you do not have it), and ask them to type
the code from the email into the code field."""


def run_tool(name, args, session):
    """Run the tool Claude asked for, for the customer in the session."""
    if name == "send_code":
        return send_code(session, args["order_number"])
    if session["customer"] is None:
        return {"error": "locked: the customer is not verified yet"}
    if name == "find_order":
        return find_order(args["number"], session["customer"])
    if name == "price":
        return price(args["product"], session)
    return delivery_status(args["tracking"])


def answer(message, session, usage=None, history=()):
    """Loop until Claude stops asking for tools."""
    messages = list(history)
    messages.append({"role": "user", "content": message})
    while True:
        response = call(
            session.get("id"),
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
                                  session)
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result)})
        messages.append({"role": "user", "content": results})
