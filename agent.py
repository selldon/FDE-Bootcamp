"""The agent loop: Claude asks for tools, our code runs them."""
import json
from dataclasses import dataclass

from llm import chat
from tools import TOOLS, delivery_status, find_order, open_case

SYSTEM = """You are the DemoStore support assistant.
Answer questions about orders with the tools, in two or three
short sentences. Never guess a date or a status. If a tool says
the customer is not verified, ask them to enter the one-time
code from their email first."""

MAX_ROUNDS = 10
HAND_OFF_REPLY = ("I have passed this to a person on our team. "
                  "They can see our chat and will take over.")


@dataclass
class Result:
    reply: str
    action: str  # "hand_off", "give_status" or "reply"
    rounds: int


def run_tool(name, args, customer):
    """Run the tool Claude asked for, for our customer."""
    if name == "find_order":
        return find_order(args["number"], customer)
    return delivery_status(args["tracking"], customer)


def answer(message, customer, usage=None, history=()):
    """Loop until Claude stops asking for tools; say what was done."""
    messages = list(history)
    messages.append({"role": "user", "content": message})
    # The case holds the chat as the customer saw it, not tool traffic.
    chat_so_far = [m for m in messages if isinstance(m["content"], str)]
    gave_status = False
    for rounds in range(1, MAX_ROUNDS + 1):
        response = chat(SYSTEM, TOOLS, messages, usage)
        if response.stop_reason != "tool_use":
            action = "give_status" if gave_status else "reply"
            return Result(response.content[-1].text, action, rounds)
        messages.append({"role": "assistant",
                         "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "hand_off":
                open_case(block.input["summary"], chat_so_far, customer)
                return Result(HAND_OFF_REPLY, "hand_off", rounds)
            result = run_tool(block.name, block.input, customer)
            gave_status = gave_status or "error" not in result
            results.append({"type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result)})
        messages.append({"role": "user", "content": results})
    open_case(f"Stopped after {MAX_ROUNDS} rounds without an answer.",
              chat_so_far, customer)
    return Result(HAND_OFF_REPLY, "hand_off", MAX_ROUNDS)
