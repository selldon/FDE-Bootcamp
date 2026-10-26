"""The chat service: the widget sends a message, we reply."""
import uuid

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from agent import answer
from intent import Intent, classify
from llm import NoAnswer
from verify import check_code

GREETING = ("Hi, I am DemoStore's AI assistant. "
            "You can ask for a person at any time.")
HANDOFF = ("I cannot answer right now, so a person from our team "
           "will take over this chat.")

app = FastAPI(title="DemoStore chat")
SESSIONS = {}


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str


class ChatOut(BaseModel):
    session_id: str
    reply: str
    intent: Intent | None


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
    try:
        intent = classify(body.message, conversation=session_id)
        reply = answer(body.message, session,
                       history=session["history"])
    except NoAnswer as error:
        print("handoff:", session_id, error)
        return ChatOut(session_id=session_id, reply=HANDOFF,
                       intent=None)
    if not session["history"]:
        reply = GREETING + "\n\n" + reply
    session["history"] += [
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": reply},
    ]
    return ChatOut(session_id=session_id, reply=reply,
                   intent=intent)


@app.post("/verify")
def verify_code(body: CodeIn) -> dict:
    """The code field under the chat: to our code, not to the model."""
    session = SESSIONS.get(body.session_id)
    if session is None:
        return {"verified": False}
    return {"verified": check_code(session, body.code)}


if __name__ == "__main__":
    uvicorn.run(app, port=8000)
