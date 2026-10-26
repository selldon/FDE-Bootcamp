"""A stand-in for the Claude API on a busy day, for the adapter lesson (FDE 1-9-3): every request gets 429 Too Many
Requests with Retry-After: 1, the way the API answers an organization that is over its rate limit.

    labs/.venv/bin/uvicorn sim:app --app-dir systems/outage --port 8050      (from the sandbox folder)

The lesson's scripts send it a dummy key, never the real one.
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Claude API stand-in: too busy")
BUSY = {"type": "error", "error": {"type": "rate_limit_error",
        "message": "Number of requests has exceeded your rate limit (stand-in)."}}


@app.post("/v1/messages")
def messages():
    return JSONResponse(BUSY, status_code=429, headers={"retry-after": "1"})
