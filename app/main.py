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
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="info")


def main():
    http_thread = threading.Thread(target=_run_http_server, daemon=True)
    http_thread.start()
    run_polling()


if __name__ == "__main__":
    main()
