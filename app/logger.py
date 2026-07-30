"""
Append-only JSONL run logger.

Every agent "run" (one incoming trigger message -> one final answer) gets
logged as a single JSON line to logs/run.jsonl. That file is served
publicly by server.py so it can be used as the `log_url` in bot replies.
"""

import json
import os
import threading
from datetime import datetime, timezone

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_PATH = os.path.join(LOG_DIR, "run.jsonl")

_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_PATH):
        open(LOG_PATH, "a").close()


def log_event(event: dict):
    """Append a single JSON object (one line) to the run log."""
    _ensure_dir()
    event = dict(event)
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    line = json.dumps(event, ensure_ascii=False, default=str)
    with _lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def log_run(chat_id, incoming_message, history, tool_trace, final_answer, log_url, error=None):
    """Convenience wrapper: log one full agent run."""
    log_event(
        {
            "type": "run",
            "chat_id": chat_id,
            "incoming_message": incoming_message,
            "history_len": len(history),
            "tool_trace": tool_trace,
            "final_answer": final_answer,
            "log_url": log_url,
            "error": error,
        }
    )
