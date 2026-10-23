"""The chat service: the widget sends a message, we reply."""
import uuid

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

import handoff
import refunds
import verify
from agent import answer
from intent import Intent, classify

GREETING = ("Hi, I am DemoStore's AI assistant. "
            "You can ask for a person at any time.")

# The only intent this build answers; "other" (greetings, follow-ups) still
# goes to the model, which hands off by itself when it must.
COVERED = {"order_status", "return_request", "other"}

app = FastAPI(title="DemoStore chat")
SESSIONS: dict[str, dict] = {}


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str


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
    return VerifyOut(session_id=session_id,
                     verified=session["customer"] is not None)


@app.post("/chat")
def chat(body: ChatIn) -> ChatOut:
    """One message in, one reply out."""
    session_id, session = get_session(body.session_id)
    ctx = refunds.Context(session["customer"], session_id, session.get("offer"),
                          session.get("failed", 0), session.get("handed_off", False))
    chat_so_far = session["history"] + [{"role": "user", "content": body.message}]
    if ctx.offer is not None and ctx.customer is not None and refunds.is_yes(body.message):
        # B15, B16: only the customer's own yes, checked here, writes a draft - the model never runs.
        intent = Intent(summary="The customer confirmed the refund request.", intent="return_request",
                        order_number=ctx.offer["order"], needs_human=False, language="en")
        reply = refunds.confirm(ctx)
    else:
        declined = ctx.offer is not None
        ctx.offer = None  # any other message drops the offer
        if declined:
            ctx.failed += 1  # decision 6: a declined or unclear reply to an offer is a failed try
        intent = classify(body.message)
        if intent["needs_human"] or intent["intent"] not in COVERED:
            # B4, B5: decided here, so no wording of the message can talk the
            # model out of it.
            reason = "needs_human" if intent["needs_human"] else "not_covered"
            reply = handoff.open_case(ctx, intent["summary"], chat_so_far, reason, reason.replace("_", " "))
        elif ctx.failed >= handoff.FAILED_LIMIT:
            reply = handoff.open_case(ctx, None, chat_so_far, "failed_tries", "two failed tries")
        else:
            reply = answer(body.message, ctx, history=session["history"]).reply
    session["offer"], session["failed"], session["handed_off"] = ctx.offer, ctx.failed, ctx.handed_off
    if not session["history"]:
        reply = GREETING + "\n\n" + reply
    session["history"] += [
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": reply},
    ]
    return ChatOut(session_id=session_id, reply=reply,
                   intent=intent)


if __name__ == "__main__":
    uvicorn.run(app, port=8000)
