"""The chat service: the widget sends a message, we reply."""
import uuid

import uvicorn
from fastapi import FastAPI
from launch import route, to_person
from metrics import numbers
from pydantic import BaseModel

from agent import answer
from intent import Intent, classify
from llm import NoAnswer
from verify import check_code

GREETING = ("Hi, I am DemoStore's AI assistant. "
            "You can ask for a person at any time.")
HANDOFF = ("I cannot answer right now, so a person from our team "
           "will take over this chat.")
PERSON = "Thank you. A person from our team will answer you here."

app = FastAPI(title="DemoStore chat")
SESSIONS = {}


class ChatIn(BaseModel):
    session_id: str | None = None
    visitor: str | None = None
    message: str


class ChatOut(BaseModel):
    session_id: str
    reply: str
    intent: Intent | None
    team: str


class CodeIn(BaseModel):
    session_id: str
    code: str


@app.post("/chat")
def chat(body: ChatIn) -> ChatOut:
    """One message in, one reply out."""
    session_id = body.session_id
    if session_id not in SESSIONS:
        session_id = str(uuid.uuid4())
        SESSIONS[session_id] = {"id": session_id, "customer": None,
                                "history": []}
    session = SESSIONS[session_id]
    team = route(session_id, body.visitor or session_id)
    if team == "control":
        to_person(session_id, body.message)
        return ChatOut(session_id=session_id, reply=PERSON,
                       intent=None, team=team)
    try:
        intent = classify(body.message, conversation=session_id)
        reply = answer(body.message, session,
                       history=session["history"])
    except NoAnswer as error:
        print("handoff:", session_id, error)
        return ChatOut(session_id=session_id, reply=HANDOFF,
                       intent=None, team=team)
    if not session["history"]:
        reply = GREETING + "\n\n" + reply
    session["history"] += [
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": reply},
    ]
    return ChatOut(session_id=session_id, reply=reply,
                   intent=intent, team=team)


@app.post("/verify")
def verify_code(body: CodeIn) -> dict:
    """The code field under the chat: to our code, not to the model."""
    session = SESSIONS.get(body.session_id)
    if session is None:
        return {"verified": False}
    return {"verified": check_code(session, body.code)}


@app.get("/pilot")
def pilot() -> dict:
    """The pilot's numbers for the team's page."""
    return numbers()


if __name__ == "__main__":
    uvicorn.run(app, port=8000)
