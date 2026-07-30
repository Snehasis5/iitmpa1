"""
Entrypoint. Runs:
  - a FastAPI server (health check + public log file) in a background thread
  - the Telegram bot polling loop in the main thread

This lets a single process/service (e.g. one Render "Web Service") both
answer Telegram messages AND serve the public log_url.
"""

import os
import threading

import uvicorn

from .server import app as fastapi_app
from .bot import run_polling


def _run_http_server():
    port = int(os.environ.get("PORT", "8000"))
    # IMPORTANT: force the stdlib asyncio loop implementation here.
    # uvicorn's default loop="auto" will pick uvloop (since uvloop is
    # installed via uvicorn[standard]) and *install it as the global,
    # process-wide asyncio event loop policy*. That happens in this
    # background thread, but the policy change is process-wide, so it
    # then breaks python-telegram-bot's run_polling() in the main
    # thread (uvloop's policy raises "There is no current event loop
    # in thread 'MainThread'" instead of auto-creating one like
    # stdlib asyncio does).
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="info", loop="asyncio")


def main():
    http_thread = threading.Thread(target=_run_http_server, daemon=True)
    http_thread.start()
    run_polling()


if __name__ == "__main__":
    main()
