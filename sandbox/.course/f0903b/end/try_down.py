"""One chat message while Claude is too busy to answer."""
import os

os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:8050"
os.environ["ANTHROPIC_API_KEY"] = "test"

from fastapi.testclient import TestClient

from app import app

reply = TestClient(app).post("/chat", json={"message": "Where is my order?"})
print(reply.status_code, reply.json()["reply"])
