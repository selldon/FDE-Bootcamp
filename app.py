"""The chat service: the widget sends a message, we reply."""
import uuid
from datetime import UTC, datetime

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

import handoff
import policy_answer
import refunds
import tools
import traces
import verify
from agent import OFFER_REPLY, answer
from intent import Intent, classify
from masking import mask_cards

GREETING = ("Hi, I am DemoStore's AI assistant. "
            "You can ask for a person at any time.")

# The only intent this build answers; "other" (greetings, follow-ups) still
# goes to the model, which hands off by itself when it must.
COVERED = {"order_status", "return_request", "policy_question", "other"}

app = FastAPI(title="DemoStore chat")
SESSIONS: dict[str, dict] = {}


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str
    market: str | None = None  # D4: where the customer is, if the site knows; a verified customer's market wins


class ChatOut(BaseModel):
    session_id: str
    reply: str
    intent: Intent


class VerifyStartIn(BaseModel):
    session_id: str | None = None
    email: str


class VerifyCheckIn(BaseModel):
    session_id: str | None = None
    email: str
    code: str


class EraseCheckIn(BaseModel):
    session_id: str | None = None
    email: str
    code: str


class EraseOut(BaseModel):
    erased: bool
    reply: str


ERASED_REPLY = ("Done: your chat records are deleted. Cases already opened with our support team "
                "are not covered yet; ask a person about those.")
NOT_ERASED_REPLY = "The code did not match, so nothing was deleted."


class VerifyOut(BaseModel):
    session_id: str
    verified: bool


def get_session(session_id: str | None) -> tuple[str, dict]:
    """The session with this id, or a new one."""
    if not session_id or session_id not in SESSIONS:
        session_id = str(uuid.uuid4())
        SESSIONS[session_id] = {"customer": None, "history": [], "offer": None, "failed": 0,
                                  "handed_off": False}
    return session_id, SESSIONS[session_id]


@app.post("/verify/start")
def verify_start(body: VerifyStartIn) -> VerifyOut:
    """Send the code. The answer is the same for every email."""
    session_id, _ = get_session(body.session_id)
    verify.start(body.email)
    return VerifyOut(session_id=session_id, verified=False)


@app.post("/verify/check")
def verify_check(body: VerifyCheckIn) -> VerifyOut:
    """The only place that sets the session's customer."""
    session_id, session = get_session(body.session_id)
    if verify.check(body.email, body.code):
        session["customer"] = body.email.strip().lower()
        session["customer_hash"] = traces.customer_hash(session["customer"])
        try:  # B23: the earlier rows of this chat now belong to her; a failed write does not block
            traces.sink().fill_hash(session_id, session["customer_hash"])
        except Exception:  # noqa: BLE001
            traces.failures += 1
    return VerifyOut(session_id=session_id,
                     verified=session["customer"] is not None)


@app.post("/erase/start")
def erase_start(body: VerifyStartIn) -> VerifyOut:
    """Send the code, as in B1: the same answer for every email."""
    return verify_start(body)


@app.post("/erase/check")
def erase_check(body: EraseCheckIn) -> EraseOut:
    """With the right code: delete her traces and her in-memory sessions, and log the count only."""
    if not verify.check(body.email, body.code):
        return EraseOut(erased=False, reply=NOT_ERASED_REPLY)
    email = body.email.strip().lower()
    ours = {sid for sid, s in SESSIONS.items() if s["customer"] == email}
    if body.session_id in SESSIONS and SESSIONS[body.session_id]["customer"] is None:
        ours.add(body.session_id)  # the chat she is typing in, not yet verified
    deleted = traces.sink().delete_customer(traces.customer_hash(email), ours)
    for sid in ours:
        del SESSIONS[sid]
    traces.sink().log_erasure(datetime.now(UTC), deleted)
    return EraseOut(erased=True, reply=ERASED_REPLY)


@app.post("/chat")
def chat(body: ChatIn) -> ChatOut:
    """One message in, one reply out."""
    session_id, session = get_session(body.session_id)
    token = traces.current_session.set(session_id)  # B22: the model calls of this turn belong to this chat
    owner = traces.current_customer.set(session.get("customer_hash"))
    try:
        return _chat(body, session_id, session)
    finally:
        traces.current_customer.reset(owner)
        traces.current_session.reset(token)


def _chat(body: ChatIn, session_id: str, session: dict) -> ChatOut:
    message = mask_cards(body.message)  # B21: first of all, so no later step can see a card number
    verified = tools.get_store().market_of(session["customer"]) if session["customer"] else None
    market = policy_answer.market_for(verified, body.market, session.get("market"))  # D4
    ctx = refunds.Context(session["customer"], session_id, session.get("offer"),
                          session.get("failed", 0), session.get("handed_off", False), market)
    chat_so_far = session["history"] + [{"role": "user", "content": message}]
    if ctx.offer is not None and ctx.customer is not None and refunds.is_yes(message):
        # B15, B16: only the customer's own yes, checked here, writes a draft - the model never runs.
        intent = Intent(summary="The customer confirmed the refund request.", intent="return_request",
                        order_number=ctx.offer["order"], needs_human=False, damaged=False, language="en")
        reply = refunds.confirm(ctx)
    else:
        declined = ctx.offer is not None
        ctx.offer = None  # any other message drops the offer
        if declined:
            ctx.failed += 1  # decision 6: a declined or unclear reply to an offer is a failed try
        intent = classify(message)
        damaged = intent["damaged"]
        if intent["needs_human"] or damaged or intent["intent"] not in COVERED:
            # B4, B5: decided here, so no wording of the message can talk the
            # model out of it. Damage on arrival is a person's case (replay C25); agent.answer keeps a
            # keyword rule as a backstop for the turns that get past the flag.
            reason = "needs_human" if intent["needs_human"] else "damaged" if damaged else "not_covered"
            reply = handoff.open_case(ctx, intent["summary"], chat_so_far, reason, reason.replace("_", " "))
        elif ctx.failed >= handoff.FAILED_LIMIT:
            reply = handoff.open_case(ctx, None, chat_so_far, "failed_tries", "two failed tries")
        else:
            result = answer(message, ctx, history=session["history"])
            reply = result.reply
            if intent["intent"] == "policy_question" and result.action == "reply" and not result.policy:
                reply = OFFER_REPLY  # B18: a policy reply that did not come from the tool is never sent
    session["offer"], session["failed"], session["handed_off"] = ctx.offer, ctx.failed, ctx.handed_off
    session["market"] = None if verified else ctx.market  # a verified customer's market is read again each turn
    if not session["history"]:
        reply = GREETING + "\n\n" + reply
    session["history"] += [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    return ChatOut(session_id=session_id, reply=reply,
                   intent=intent)


if __name__ == "__main__":
    uvicorn.run(app, port=8000)
