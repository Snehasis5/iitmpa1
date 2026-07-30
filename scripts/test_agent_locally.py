"""
Quick local test: run the agent (DeepSeek + tools) on a sample question
without going through Telegram at all. Useful for iterating fast.

Usage:
  export DEEPSEEK_API_KEY=sk-...
  python scripts/test_agent_locally.py "Which state has the highest maternal mortality rate based on MOSPI data? Reply with ONLY this JSON object and nothing else: {\"answer\": {\"state\": \"<state name>\"}, \"log_url\": \"<url>\"}"
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent import run_agent  # noqa: E402


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "What is 2 + 2? Reply with ONLY this JSON: {\"answer\": <number>}"
    history = [{"role": "user", "content": question}]
    answer_obj, raw, trace = run_agent(history)
    print("=== TOOL TRACE ===")
    for t in trace:
        print(json.dumps(t, indent=2, default=str)[:2000])
    print("=== RAW FINAL TEXT ===")
    print(raw)
    print("=== PARSED ANSWER ===")
    print(json.dumps(answer_obj, indent=2))


if __name__ == "__main__":
    main()
