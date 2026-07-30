# TDS P1 — Data Analyst Telegram Bot (DeepSeek-powered)

An LLM agent that answers to a Telegram message containing a data-analysis
question and replies with **exactly one JSON object**:

```json
{"answer": <shape the question asked for>, "log_url": "https://your-host/logs/run.jsonl"}
```

Model: **DeepSeek** (`deepseek-chat`, OpenAI-compatible API) with function
calling / tool use so it can actually fetch and compute over real public
data (MOSPI, data.gov.in, raw CSVs on GitHub, etc.) instead of guessing.

## How it works

```
Telegram message
      │
      ▼
app/bot.py        - keeps a short per-chat history (for multi-turn tasks)
                    - only *answers* once a message looks like the final
                      "reply with ONLY this JSON" trigger
      │
      ▼
app/agent.py      - DeepSeek chat-completions + tool-calling loop
      │
      ├─ web_search   (DuckDuckGo, no API key needed)
      ├─ fetch_url    (raw HTML/CSV/JSON fetch)
      └─ python_exec  (sandboxed pandas/numpy/requests — downloads and
                        computes over the actual dataset)
      │
      ▼
app/logger.py     - appends one JSON line per run to logs/run.jsonl
app/server.py     - serves that file publicly at /logs/run.jsonl
```

Both the Telegram polling loop and the small FastAPI log server run in a
single process (`app/main.py`), so one deployed service gives you both
the bot AND a public, wget-able `log_url`.

## Multi-turn handling

Some grading tasks send a short sequence of messages before the real
question. `bot.py` stores every incoming message in an in-memory
per-chat history, but only actually invokes the agent + replies once a
message looks like the final trigger (it contains `log_url` or a
"reply with only this JSON" instruction — see `TRIGGER_RE` in
`app/bot.py`). When it does trigger, the full stored history is passed
to the agent, so earlier inline data/context is used to answer the
last message. Tune `TRIGGER_RE` if you see it misfire during testing.

## 1. Local setup

```bash
git clone <this-repo-url>
cd tds-p1-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN, DEEPSEEK_API_KEY, PUBLIC_BASE_URL (after deploy)
```

Get a `TELEGRAM_BOT_TOKEN` from [@BotFather](https://t.me/BotFather)
(`/newbot`) — the resulting username must end in `bot`.

Get a `DEEPSEEK_API_KEY` from https://platform.deepseek.com.

### Test the agent alone (no Telegram needed)

```bash
export DEEPSEEK_API_KEY=sk-...
python scripts/test_agent_locally.py \
  'Which state has the highest maternal mortality rate based on MOSPI data? Reply with ONLY this JSON object and nothing else: {"answer": {"state": "<state name>"}, "log_url": "<url>"}'
```

### Run the full bot locally

```bash
python -m app.main
```

This starts:
- the Telegram polling loop (message the bot on Telegram to test it)
- an HTTP server on `$PORT` (default 8000) serving `/logs/run.jsonl`

Message your bot on Telegram and confirm it replies with a single JSON
object, and that `curl localhost:8000/logs/run.jsonl` shows the run.

## 2. Deploy (Render.com example — free tier friendly)

1. Push this repo to GitHub (public).
2. On [render.com](https://render.com): **New +** → **Web Service** →
   connect your repo. Render will detect `render.yaml`/`Dockerfile`
   automatically (or set: Environment = Docker).
3. Add environment variables in the Render dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `DEEPSEEK_API_KEY`
   - `DEEPSEEK_BASE_URL` = `https://api.deepseek.com`
   - `DEEPSEEK_MODEL` = `deepseek-chat`
   - `PUBLIC_BASE_URL` = the URL Render gives you, e.g.
     `https://tds-p1-data-analyst-bot.onrender.com`
     (set this *after* the first deploy once you know the URL, then
     redeploy)
4. Deploy. Once live, your `log_url` will be:
   `https://tds-p1-data-analyst-bot.onrender.com/logs/run.jsonl`

Any other host works the same way (Railway, Fly.io, a VPS with
`docker run`, etc.) — the only requirements are: the process stays
running (long-polling Telegram bot), and port `$PORT` is publicly
reachable for the log file.

> Free-tier web services on some PaaS providers sleep after inactivity,
> which would make your bot briefly unresponsive to the first message
> after a while. If reliability during grading matters, use a
> low-cost "always on" plan/instance, or a small VPS with
> `docker run -d --restart unless-stopped ...`.

## 3. Validate against the public grading harness

```bash
git clone https://github.com/Jivraj-18/tds-p1-t2-2026-telegram-bot
cd tds-p1-t2-2026-telegram-bot
# follow its README to point it at your bot's Telegram username
# add your own sample questions to evals/questions.json to test locally
```

## 4. Register

Submit, comma-separated:
```
https://github.com/<you>/<this-repo>, your_telegram_bot
```

## Notes / things to tune before grading

- `TRIGGER_RE` in `app/bot.py` — the heuristic for "this message wants
  a final JSON reply". Broaden/narrow it based on how the grader's
  multi-turn messages look in your own testing.
- `python_exec` in `app/tools.py` is a plain `exec()` sandbox (pandas/
  numpy/requests only) — fine for a grading task, but don't expose this
  service to arbitrary untrusted users beyond the grader.
- `MAX_TOOL_ROUNDS` in `app/agent.py` caps tool-call rounds per
  question; raise it if questions need more multi-step data wrangling.
- History is in-memory (`collections.deque`) and resets on restart —
  fine for short-lived grading runs; swap for Redis/SQLite if you need
  durability across restarts.
