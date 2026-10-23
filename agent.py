"""The agent loop: Claude asks for tools, our code runs them."""
import json
from dataclasses import dataclass

import refunds
from llm import chat
from tools import TOOLS, delivery_status, find_order, open_case

SYSTEM = """You are the DemoStore support assistant.
Answer questions about orders with the tools, in two or three
short sentences. Never guess a date or a status. If a tool says
the customer is not verified, ask them to enter the one-time
code from their email first.
If the customer asks about an order but gives no order number, ask
for it. Do not guess one.
You report the status and promised date of an order, and you can
check whether one item of an order can be returned.
For a return, call prepare_return with the order number, the line
and, only if the customer said so, whether the item was opened. If
the line is not clear, ask the customer which item. Explain the
decision and the amount from the tool result in your own words:
you never make the decision yourself, never promise an exception,
never say the refund is done or paid, and never say how long it
takes. If the decision is eligible, tell the customer the amount
and ask whether they want to send the refund request for approval.
If the tool says ask opened, ask whether the item was opened. If
it says person, call hand_off.
For anything else - changing an order or its address, exchanges,
policies, products - do not try to answer: call hand_off. Also call hand_off when the customer is angry or asks
for a person.
Dates and statuses come only from the tools, never from memory.
If a tool result has offer_person set, the carrier's news is out of
date: give no delivery date, say the news is old, and offer to pass
the chat to a person.
Never promise money: no refunds, credits or compensation."""

MAX_ROUNDS = 10
HAND_OFF_REPLY = ("I have passed this to a person on our team. "
                  "They can see our chat and will take over.")


@dataclass
class Result:
    reply: str
    action: str  # "hand_off", "give_status" or "reply"
    rounds: int


def run_tool(name, args, ctx):
    """Run the tool Claude asked for, for the customer of this chat."""
    if name == "find_order":
        return find_order(args["number"], ctx.customer)
    if name == "prepare_return":
        return refunds.prepare_return(args.get("number"), args.get("line"), args.get("opened"), ctx)
    return delivery_status(args["tracking"], ctx.customer)


def answer(message, ctx, usage=None, history=()):
    """Loop until Claude stops asking for tools; say what was done. `ctx` is a `refunds.Context`."""
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
                open_case(block.input["summary"], chat_so_far, ctx.customer)
                return Result(HAND_OFF_REPLY, "hand_off", rounds)
            result = run_tool(block.name, block.input, ctx)
            if block.name != "prepare_return":
                gave_status = gave_status or "error" not in result
            results.append({"type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result)})
        messages.append({"role": "user", "content": results})
    open_case(f"Stopped after {MAX_ROUNDS} rounds without an answer.",
              chat_so_far, ctx.customer)
    return Result(HAND_OFF_REPLY, "hand_off", MAX_ROUNDS)
