"""The chat service: the widget sends a message, we reply."""
import uuid

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from agent import answer
from intent import Intent, classify

GREETING = ("Hi, I am DemoStore's AI assistant. "
            "You can ask for a person at any time.")

app = FastAPI(title="DemoStore chat")
SESSIONS = {}


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str


class ChatOut(BaseModel):
    session_id: str
    reply: str
    intent: Intent


@app.post("/chat")
def chat(body: ChatIn) -> ChatOut:
    """One message in, one reply out."""
    session_id = body.session_id
    if session_id not in SESSIONS:
        session_id = str(uuid.uuid4())
        SESSIONS[session_id] = {"customer": None, "history": []}
    session = SESSIONS[session_id]
    intent = classify(body.message)
    reply = answer(body.message, session["customer"],
                   history=session["history"])
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
