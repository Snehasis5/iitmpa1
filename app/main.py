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

    # Explicitly create and set event loop (FIX)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    run_polling()


if __name__ == "__main__":
    main()
