"""
Minimal HTTP server. Its only job is to:
  1. Serve /logs/run.jsonl publicly (wget-able), so it can be used as
     the `log_url` field in the bot's JSON replies.
  2. Provide a basic / healthcheck endpoint (useful for Render/Railway
     health checks, and to keep a free-tier web service alive).
"""

import os

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, FileResponse

from .logger import LOG_PATH, _ensure_dir

app = FastAPI()


@app.get("/")
def health():
    return {"status": "ok", "service": "tds-p1-data-analyst-bot"}


@app.get("/logs/run.jsonl")
def get_log():
    _ensure_dir()
    return FileResponse(LOG_PATH, media_type="application/jsonl", filename="run.jsonl")
