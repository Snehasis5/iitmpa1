"""
Telegram bot front-end.

- Maintains a short in-memory conversation history per chat_id.
- Only triggers the agent when a "final answer" instruction is detected.
- Always replies with exactly one JSON object including a log_url.
"""

import json
import logging
import os
import re
import asyncio
from collections import defaultdict, deque

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from .agent import run_agent
from .logger import log_run

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
LOG_URL = (
    f"{PUBLIC_BASE_URL}/logs/run.jsonl"
    if PUBLIC_BASE_URL
    else "https://your-host/run.jsonl"
)

# chat_id -> deque of {"role": ..., "content": ...}
HISTORY = defaultdict(lambda: deque(maxlen=30))

TRIGGER_RE = re.compile(
    r"log_url|reply with only this json|reply with only the json",
    re.IGNORECASE,
)


def is_trigger_message(text: str) -> bool:
    return bool(TRIGGER_RE.search(text))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or not message.text:
        return

    chat_id = update.effective_chat.id
    text = message.text

    history = HISTORY[chat_id]
    history.append({"role": "user", "content": text})

    if not is_trigger_message(text):
        logger.info("Stored context message for chat %s (no reply).", chat_id)
        return

    tool_trace = []
    answer_obj = None
    error = None

    try:
        # Run blocking agent safely in a thread
        answer_obj, raw_final, tool_trace = await asyncio.wait_for(
            asyncio.to_thread(run_agent, list(history)),
            timeout=30,
        )
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        logger.exception("Agent run failed")

    if answer_obj is None:
        answer_obj = {"answer": None}

    if "log_url" not in answer_obj:
        answer_obj["log_url"] = LOG_URL

    reply_text = json.dumps(answer_obj, ensure_ascii=False)

    # Telegram message size safety (~4096 limit)
    if len(reply_text) > 4000:
        reply_text = reply_text[:4000]

    history.append({"role": "assistant", "content": reply_text})

    log_run(
        chat_id=chat_id,
        incoming_message=text,
        history=list(history),
        tool_trace=tool_trace,
        final_answer=answer_obj,
        log_url=LOG_URL,
        error=error,
    )

    await message.reply_text(reply_text)


def build_application() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    return app


def run_polling():
    app = build_application()
    logger.info("Starting Telegram bot polling...")
    app.run_polling(drop_pending_updates=True)
