"""
The data-analyst agent.

Uses DeepSeek's OpenAI-compatible chat completions API with function
calling. Given the full conversation history for a Telegram chat, it
runs a tool-use loop (web_search / fetch_url / python_exec) until the
model produces a final answer, then extracts the single JSON object the
question asked for.
"""

import json
import os
import re

from openai import OpenAI

from .tools import TOOL_SPECS, TOOL_IMPLS

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

SYSTEM_PROMPT = """You are a meticulous data-analyst agent operating over Telegram.

You will be given a conversation. The last user message contains a data-analysis
question. It will explicitly specify the exact JSON shape you must answer with,
e.g. {"answer": {"state": "<state name>"}, "log_url": "<url>"}.

Rules:
1. Work out the answer using real data. If the question references a public
   dataset (MOSPI, data.gov.in, github raw CSVs, etc.) or gives inline data,
   use the python_exec tool (pandas/numpy/requests available) to actually
   download/parse it and compute the answer numerically. Use web_search /
   fetch_url to locate a dataset URL if one isn't given directly.
2. IMPORTANT: web_search can fail or return zero results (rate limiting,
   markup changes, etc). If a web_search call returns an empty "results"
   list, do NOT just repeat the same or a similar search again and again.
   After at most 2 failed search attempts, stop searching and either:
     a) try fetch_url / python_exec directly on a specific URL you already
        know or can infer (official source, a raw CSV/API endpoint), or
     b) if no data can be retrieved after reasonable effort, answer using
        your own best domain knowledge of well-known public statistics
        (e.g. published SRS/MOSPI figures you already know) rather than
        leaving the answer blank.
3. Never spend more than ~4-5 tool calls total on a single question unless
   you are making clear forward progress (e.g. successfully parsing a
   dataset). Prefer producing a best-effort final answer over exhausting
   the tool budget with repeated failing calls.
4. Do not guess or hallucinate specific numbers if you can compute them
   from real data you successfully retrieved. But if data truly cannot be
   retrieved, give your best evidence-based estimate rather than refusing
   or returning null.
5. Once you have the final answer, respond with ONLY the JSON object the
   question asked for (matching its exact keys/shape) and nothing else -
   no markdown fences, no explanation. Do NOT include "log_url" yourself;
   the calling code will attach it. So output only the "answer" portion
   wrapped exactly as requested, e.g. if asked for
   {"answer": {...}, "log_url": "..."} just output {"answer": {...}}.
   Rules:
 1. Work out the answer using real data. If the question references a public
    dataset (MOSPI, data.gov.in, github raw CSVs, etc.) or gives inline data,
    use the python_exec tool (pandas/numpy/requests available) to actually
    download/parse it and compute the answer numerically. Use web_search /
-   fetch_url to locate a dataset URL if one isn't given directly.
+   fetch_url to locate a dataset URL if one isn't given directly. For Indian
+   government statistics (MOSPI, health, census, economic indicators), prefer
+   the data_gov_in_resource tool over guessing file paths on mospi.gov.in —
+   web_search 'site:data.gov.in <topic>' first to find the resource_id (the
+   UUID in the dataset's page/API URL), then call data_gov_in_resource with it.
 2. IMPORTANT: web_search can fail or return zero results (rate limiting,
    markup changes, etc). If a web_search call returns an empty "results"
    list, do NOT just repeat the same or a similar search again and again.
    After at most 2 failed search attempts, stop searching and either:
      a) try fetch_url / python_exec directly on a specific URL you already
         know or can infer (official source, a raw CSV/API endpoint), or
      b) if no data can be retrieved after reasonable effort, answer using
         your own best domain knowledge of well-known public statistics
         (e.g. published SRS/MOSPI figures you already know) rather than
         leaving the answer blank.
+6. Before falling back to (2b), you must have tried at least one of
+   data_gov_in_resource or fetch_url on a real URL in this conversation —
+   don't skip straight from a failed web_search to guessing.
"""

MAX_TOOL_ROUNDS = 10
# Once we've made this many tool calls total without a final answer, tell
# the model (via a synthetic system nudge) to wrap up on the next turn.
NUDGE_AFTER_CALLS = 6


def _to_openai_messages(history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})
    return messages


def _extract_json_object(text: str):
    """Best-effort extraction of the first {...} JSON object in text."""
    text = text.strip()
    # strip markdown fences if present
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # fall back: find the first balanced {...} block
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    return None
    return None


def run_agent(history):
    """
    history: list of {"role": "user"|"assistant", "content": str}
    Returns: (answer_obj_or_none, raw_final_text, tool_trace: list)
    """
    messages = _to_openai_messages(history)
    tool_trace = []
    total_calls = 0
    nudged = False

    for round_i in range(MAX_TOOL_ROUNDS):
        # Force a final answer on the very last allowed round.
        force_final = round_i == MAX_TOOL_ROUNDS - 1
        tool_choice = "none" if force_final else "auto"

        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            tools=TOOL_SPECS,
            tool_choice=tool_choice,
            temperature=0,
        )
        msg = resp.choices[0].message

        if msg.tool_calls and not force_final:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                impl = TOOL_IMPLS.get(name)
                if impl is None:
                    result = {"error": f"unknown tool {name}"}
                else:
                    result = impl(**args)
                total_calls += 1
                tool_trace.append({"tool": name, "args": args, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str)[:6000],
                    }
                )

            if total_calls >= NUDGE_AFTER_CALLS and not nudged:
                nudged = True
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You have used several tool calls already. Stop searching/"
                            "fetching further and give your best-effort final answer now, "
                            "as ONLY the requested JSON object."
                        ),
                    }
                )
            continue

        # no tool calls (or forced) -> final answer
        final_text = msg.content or ""
        parsed = _extract_json_object(final_text)
        return parsed, final_text, tool_trace

    return None, "MAX_TOOL_ROUNDS exceeded without final answer", tool_trace