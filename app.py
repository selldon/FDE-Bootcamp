"""The chat service: the widget sends a message, we reply."""
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

import golive
import handoff
import pilot
import policy_answer
import refunds
import tools
import traces
import verify
from agent import OFFER_REPLY, answer
from golive import ASSISTANT, CONTROL, PERSON, GoLiveStore
from intent import Intent, classify, handoff_reason
from masking import mask_cards
from shadow import ShadowStore

GREETING = ("Hi, I am DemoStore's AI assistant. "
            "You can ask for a person at any time.")

app = FastAPI(title="DemoStore chat")
SESSIONS: dict[str, dict] = {}


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str
    market: str | None = None  # D4: where the customer is, if the site knows; a verified customer's market wins
    visitor_id: str | None = None  # who is on the site; the group comes from it. Without one, the session id is used
    simulated: bool = False  # traffic from the go-live simulator: every row it makes is labelled
    sim_day: int | None = None  # the simulated day, 1-14


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


@lru_cache
def golive_store() -> GoLiveStore:
    return GoLiveStore()


record_failures = 0  # go-live rows that could not be written; a failed write never blocks a chat

PASSED_ON = Intent(summary="Passed to a person without the assistant.", intent="other", order_number=None,
                   needs_human=True, damaged=False, language="en")


def live_settings() -> dict:
    """The launch settings, read now. If they cannot be read, the assistant is off: a person is the safe side."""
    try:
        return golive_store().settings()
    except Exception:  # noqa: BLE001
        return {"share": 0.0, "intents": [], "on": False}


@app.post("/chat")
def chat(body: ChatIn) -> ChatOut:
    """One message in, one reply out. A new chat is routed first: assistant, control (a person) or a person."""
    session_id, session = get_session(body.session_id)
    token = traces.current_session.set(session_id)  # B22: the model calls of this turn belong to this chat
    owner = traces.current_customer.set(session.get("customer_hash"))
    try:
        return _route(body, session_id, session)
    finally:
        traces.current_customer.reset(owner)
        traces.current_session.reset(token)


def _route(body: ChatIn, session_id: str, session: dict) -> ChatOut:
    settings = live_settings()  # at every message, so the switch works without a deploy
    new = "group" not in session
    if new:
        session["visitor_id"] = body.visitor_id or session_id
        session["group"] = golive.group_of(session["visitor_id"], settings["share"]) if settings["on"] else PERSON
        session["usage"] = []  # the model calls of the whole chat
    group = session["group"]
    if group == ASSISTANT and not settings["on"]:
        # B24: switched off while this chat is open: it goes to a person with everything said so far, never dropped.
        session["group"] = group = PERSON
        return _to_person(body, session_id, session, "switched_off", "the assistant was switched off", new)
    if group == CONTROL:
        return _to_person(body, session_id, session, None, "", new)
    if group == PERSON:
        return _to_person(body, session_id, session, "switched_off", "the assistant is not live", new)
    return _chat(body, session_id, session, settings, new)


def _to_person(body: ChatIn, session_id: str, session: dict, reason: str | None, trigger: str, new: bool) -> ChatOut:
    """A turn with no assistant: the chat goes to the live queue (control) or becomes a case (reason given)."""
    message = mask_cards(body.message)
    chat_so_far = session["history"] + [{"role": "user", "content": message}]
    ctx = refunds.Context(session.get("customer"), session_id, None, session.get("failed", 0),
                          session.get("handed_off", False), None)
    if reason is None:
        reply = handoff.open_queue(ctx, chat_so_far)
    else:
        reply = handoff.open_case(ctx, None, chat_so_far, reason, trigger)
    session["handed_off"] = ctx.handed_off
    session["history"] += [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
    _record(body, session_id, session, None, "queued" if session["group"] == CONTROL else "handed_off", new)
    return ChatOut(session_id=session_id, reply=reply, intent=PASSED_ON)


def _record(body: ChatIn, session_id: str, session: dict, intent: str | None, outcome: str, new: bool) -> None:
    """One `golive_chats` row per chat: made at its first message, brought up to date at every later one."""
    global record_failures
    tokens = golive_tokens(session["usage"])
    fields = {"group_name": session["group"], "outcome": outcome, "handed_off": session.get("handed_off", False),
              **tokens}
    if intent:
        fields["intent"] = intent
    try:
        store = golive_store()
        if new:
            store.save_chat({"visitor_id": session["visitor_id"], "chat_id": session_id, "simulated": body.simulated,
                             "sim_day": body.sim_day, **fields})
        else:
            store.update_chat(session_id, **fields)
    except Exception:  # noqa: BLE001
        record_failures += 1


def golive_tokens(usage: list) -> dict:
    """Tokens and cost of the model calls of this chat so far (None when there were none: never 0)."""
    if not usage:
        return {"input_tokens": None, "output_tokens": None, "cost": None}
    tokens_in, tokens_out = sum(u.input_tokens for u in usage), sum(u.output_tokens for u in usage)
    return {"input_tokens": tokens_in, "output_tokens": tokens_out,
            "cost": pilot.chat_cost({"input_tokens": tokens_in, "output_tokens": tokens_out})}


def _chat(body: ChatIn, session_id: str, session: dict, settings: dict, new: bool) -> ChatOut:
    usage = session["usage"]
    message = mask_cards(body.message)  # B21: first of all, so no later step can see a card number
    verified = tools.get_store().market_of(session["customer"]) if session["customer"] else None
    market = policy_answer.market_for(verified, body.market, session.get("market"))  # D4
    ctx = refunds.Context(session["customer"], session_id, session.get("offer"),
                          session.get("failed", 0), session.get("handed_off", False), market)
    chat_so_far = session["history"] + [{"role": "user", "content": message}]
    confirmed, result, asked = False, None, None  # asked: the intent name of this message
    if ctx.offer is not None and ctx.customer is not None and refunds.is_yes(message):
        confirmed = True
        # B15, B16: only the customer's own yes, checked here, writes a draft - the model never runs.
        intent = Intent(summary="The customer confirmed the refund request.", intent="return_request",
                        order_number=ctx.offer["order"], needs_human=False, damaged=False, language="en")
        reply = refunds.confirm(ctx)
    else:
        declined = ctx.offer is not None
        ctx.offer = None  # any other message drops the offer
        if declined:
            ctx.failed += 1  # decision 6: a declined or unclear reply to an offer is a failed try
        intent = classify(message, usage=usage)
        asked = intent["intent"]
        reason = handoff_reason(intent)
        if new and intent["intent"] not in settings["intents"]:
            # An intent that is not live goes to a person as it did before the assistant (decided from the first message).
            session["group"] = PERSON
            reply = handoff.open_case(ctx, intent["summary"], chat_so_far, reason or "not_live", "not live")
        elif reason:
            # B4, B5: decided here, so no wording of the message can talk the
            # model out of it. Damage on arrival is a person's case (replay C25); agent.answer keeps a
            # keyword rule as a backstop for the turns that get past the flag.
            reply = handoff.open_case(ctx, intent["summary"], chat_so_far, reason, reason.replace("_", " "))
        elif ctx.failed >= handoff.FAILED_LIMIT:
            reply = handoff.open_case(ctx, None, chat_so_far, "failed_tries", "two failed tries")
        else:
            result = answer(message, ctx, usage=usage, history=session["history"])
            reply = result.reply
            if intent["intent"] == "policy_question" and result.action == "reply" and not result.policy:
                reply = OFFER_REPLY  # B18: a policy reply that did not come from the tool is never sent
    session["offer"], session["failed"], session["handed_off"] = ctx.offer, ctx.failed, ctx.handed_off
    session["market"] = None if verified else ctx.market  # a verified customer's market is read again each turn
    reply = mask_cards(reply)  # B21: a number the model repeats is never kept or shown either
    if not session["history"]:
        reply = GREETING + "\n\n" + reply
    session["history"] += [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    outcome = "handed_off" if ctx.handed_off else "draft" if confirmed else result.action if result else "reply"
    _record(body, session_id, session, asked if new else None, outcome, new)
    return ChatOut(session_id=session_id, reply=reply,
                   intent=intent)


# ---- the pilot page: reads the shadow store, writes only marks -------------------------------------------------

SAMPLE_SIZE = 10
PUBLIC_FIELDS = ("number", "opened_at", "market", "intent", "action")  # never `opened_for`: that is the customer's email
MASKED_FIELDS = ("message", "answer", "agent_reply")  # masked again here: rows from before the masking may hold a card


@lru_cache
def pilot_store() -> ShadowStore:
    return ShadowStore()


PilotStore = Annotated[ShadowStore, Depends(pilot_store)]  # tests replace pilot_store with a FakeShadowStore


class MarkIn(BaseModel):
    number: str
    marker: str
    verdict: Literal["same", "better", "worse", "wrong"]
    sounded_sure: bool = False


def public_chat(row: dict) -> dict:
    """A stored chat as the page may see it: the listed fields only, texts masked."""
    return {**{f: row.get(f) for f in PUBLIC_FIELDS},
            **{f: mask_cards(row[f]) if row.get(f) else row.get(f) for f in MASKED_FIELDS}}


@app.get("/api/pilot")
def pilot_numbers(store: PilotStore) -> dict:
    data = pilot.numbers(store, datetime.now(UTC))
    return {**data, "sentences": pilot.sentences(data)}


@app.get("/api/pilot/sample")
def pilot_sample(store: PilotStore) -> list[dict]:
    return [public_chat(r) for r in store.sample(SAMPLE_SIZE, datetime.now(UTC).date())]


@app.post("/api/pilot/mark")
def pilot_mark(body: MarkIn, store: PilotStore) -> dict:
    try:
        store.mark(body.number, body.marker, body.verdict, body.sounded_sure)
    except ValueError as err:  # an empty name, sounded_sure without wrong, a number we do not have
        raise HTTPException(status_code=422, detail=str(err)) from err
    return next(m for m in store.marks(body.number) if m["marker"] == body.marker.strip())


if __name__ == "__main__":
    uvicorn.run(app, port=8000)
