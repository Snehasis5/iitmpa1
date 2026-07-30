import os
import threading
import asyncio

import uvicorn

from .server import app as fastapi_app
from .bot import run_polling


def _run_http_server():
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="info")


def main():
    # Start FastAPI in background thread
    http_thread = threading.Thread(target=_run_http_server, daemon=True)
    http_thread.start()

    # Create and set event loop, then run async bot properly
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(run_polling())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
