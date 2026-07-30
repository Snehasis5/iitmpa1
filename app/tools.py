"""
Tools the agent can call to actually solve data-analysis questions.

Changes vs the original version:
- web_search now tries `ddgs` (the maintained duckduckgo-search library,
  which handles DDG's anti-bot page properly) FIRST, falls back to the
  raw lite/html scrape, and finally falls back to Wikipedia's search API
  (which is never blocked and is great for "which state has the
  highest X" style factual questions).
- New tool: data_gov_in_resource — hits api.data.gov.in directly, which
  is how MOSPI/data.gov.in datasets are actually meant to be consumed.
  Uses the public DEMO-style key that data.gov.in issues for exactly
  this kind of exploration (documented across their own tutorials).
  Set DATA_GOV_IN_API_KEY env var to override with your own free key
  from https://data.gov.in/user/register for higher rate limits.
- fetch_url now flags binary content types instead of returning garbage
  text, so the model knows to fetch it via python_exec + pandas instead.
"""

import contextlib
import io
import json
import os
import traceback

import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup

# Publicly documented demo key from data.gov.in's own developer docs.
# Rate-limited but fine for a grading bot doing a handful of lookups.
# Get your own free key at https://data.gov.in/user/register for
# production use.
DATA_GOV_IN_API_KEY = os.environ.get(
    "DATA_GOV_IN_API_KEY",
    "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b",
)

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web and return top result titles, snippets and URLs. "
                "Tries ddgs first, then a raw DDG scrape, then Wikipedia search as "
                "a last resort. Use this to find where a public dataset "
                "(e.g. MOSPI, data.gov.in) lives, or a fact you don't know. "
                "If this still returns zero results after 2 attempts, stop "
                "searching and try data_gov_in_resource or fetch_url on a "
                "known URL instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "data_gov_in_resource",
            "description": (
                "Query a data.gov.in / MOSPI open-data resource directly via the "
                "official API (api.data.gov.in/resource/{resource_id}). Use this "
                "for Indian government statistical data (MOSPI, health, census, "
                "economic indicators, etc). If you don't know the resource_id, "
                "web_search for 'site:data.gov.in <topic>' first to find it — the "
                "resource_id is the UUID in the dataset's URL/API tab."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "The dataset's resource UUID from data.gov.in",
                    },
                    "filters": {
                        "type": "object",
                        "description": "Optional field:value filters, e.g. {\"state\": \"Assam\"}",
                    },
                    "limit": {"type": "integer", "default": 500},
                },
                "required": ["resource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch a URL and return its raw text content (truncated if huge). Use for HTML pages, CSV/JSON endpoints, etc. For binary spreadsheet files (.xlsx) prefer downloading inside python_exec with requests/pandas instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 8000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python_exec",
            "description": (
                "Execute Python code in a sandbox that has pandas (pd), numpy (np), "
                "requests, io, json, re already imported. Use this to download CSV/Excel "
                "files (e.g. from MOSPI, data.gov.in, github raw links) with requests/pandas "
                "and compute the actual answer. Set a variable named `result` to whatever "
                "you want returned (it will be JSON-stringified; use .to_dict() on "
                "DataFrames/Series). Anything printed with print() is also captured."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python source code to execute."}
                },
                "required": ["code"],
            },
        },
    },
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# web_search: ddgs -> raw DDG scrape -> Wikipedia, in that order
# ---------------------------------------------------------------------------

def _search_ddgs(query: str, max_results: int):
    from ddgs import DDGS  # pip install ddgs

    with DDGS() as ddgs:
        raw = list(ddgs.text(query, max_results=max_results))
    return [
        {
            "title": r.get("title", ""),
            "snippet": r.get("body", ""),
            "url": r.get("href", ""),
        }
        for r in raw
    ]


def _search_lite(query: str, max_results: int):
    resp = requests.post(
        "https://lite.duckduckgo.com/lite/",
        data={"q": query},
        headers=_HEADERS,
        timeout=15,
    )
    soup = BeautifulSoup(resp.text, "lxml")
    results = []
    for a in soup.select("a.result-link"):
        title = a.get_text(strip=True)
        url = a.get("href", "")
        snippet_el = a.find_parent("tr")
        snippet = ""
        if snippet_el:
            next_row = snippet_el.find_next_sibling("tr")
            if next_row:
                snippet_td = next_row.select_one(".result-snippet")
                if snippet_td:
                    snippet = snippet_td.get_text(strip=True)
        if title:
            results.append({"title": title, "snippet": snippet, "url": url})
        if len(results) >= max_results:
            break
    return results, resp.status_code, len(resp.text)


def _search_wikipedia(query: str, max_results: int):
    resp = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": max_results,
        },
        headers=_HEADERS,
        timeout=15,
    )
    data = resp.json()
    results = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        snippet = BeautifulSoup(item.get("snippet", ""), "lxml").get_text()
        results.append(
            {
                "title": title,
                "snippet": snippet,
                "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
            }
        )
    return results


def web_search(query: str, max_results: int = 5):
    # 1. ddgs library (handles DDG's anti-bot page properly)
    try:
        results = _search_ddgs(query, max_results)
        if results:
            return {"results": results, "source": "ddgs"}
    except Exception as e:
        ddgs_error = f"{type(e).__name__}: {e}"
    else:
        ddgs_error = None

    # 2. raw scrape fallback
    try:
        results, status, raw_len = _search_lite(query, max_results)
        if results:
            return {"results": results, "source": "ddg_lite_scrape"}
    except Exception as e:
        status, raw_len = None, None

    # 3. Wikipedia — never blocked, good for factual lookups
    try:
        results = _search_wikipedia(query, max_results)
        if results:
            return {"results": results, "source": "wikipedia"}
    except Exception as e:
        wiki_error = f"{type(e).__name__}: {e}"
    else:
        wiki_error = None

    return {
        "results": [],
        "note": (
            "All search backends (ddgs, DDG scrape, Wikipedia) returned nothing. "
            "Stop searching — try data_gov_in_resource or fetch_url on a specific "
            "known URL instead."
        ),
        "diagnostics": {
            "ddgs_error": ddgs_error,
            "ddg_lite_status": status,
            "ddg_lite_raw_len": raw_len,
            "wikipedia_error": wiki_error,
        },
    }


# ---------------------------------------------------------------------------
# data.gov.in / MOSPI direct API access
# ---------------------------------------------------------------------------

def data_gov_in_resource(resource_id: str, filters: dict = None, limit: int = 500):
    try:
        params = {
            "api-key": DATA_GOV_IN_API_KEY,
            "format": "json",
            "limit": limit,
        }
        if filters:
            for k, v in filters.items():
                params[f"filters[{k}]"] = v
        resp = requests.get(
            f"https://api.data.gov.in/resource/{resource_id}",
            params=params,
            headers=_HEADERS,
            timeout=20,
        )
        try:
            data = resp.json()
        except Exception:
            return {
                "status_code": resp.status_code,
                "error": "Non-JSON response",
                "raw": resp.text[:2000],
            }
        return {
            "status_code": resp.status_code,
            "total": data.get("total"),
            "count": data.get("count"),
            "records": data.get("records", [])[:limit],
            "field_names": [f.get("name") for f in data.get("field", [])] if data.get("field") else None,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# fetch_url
# ---------------------------------------------------------------------------

_BINARY_CONTENT_TYPES = (
    "spreadsheet", "excel", "octet-stream", "zip", "pdf", "vnd.ms",
)


def fetch_url(url: str, max_chars: int = 8000):
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        ctype = resp.headers.get("Content-Type", "")
        if any(b in ctype.lower() for b in _BINARY_CONTENT_TYPES) or url.lower().endswith(
            (".xlsx", ".xls", ".pdf", ".zip")
        ):
            return {
                "status_code": resp.status_code,
                "content_type": ctype,
                "note": (
                    "This is a binary file. Don't fetch_url it as text — use "
                    "python_exec with pandas.read_excel(requests.get(url).content "
                    "via io.BytesIO(...)) or similar to actually parse it."
                ),
            }
        text = resp.text
        truncated = len(text) > max_chars
        return {
            "status_code": resp.status_code,
            "content": text[:max_chars],
            "truncated": truncated,
            "content_type": ctype,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def python_exec(code: str):
    stdout = io.StringIO()
    sandbox_globals = {
        "pd": pd,
        "np": np,
        "requests": requests,
        "io": io,
        "json": json,
        "__builtins__": __builtins__,
    }
    sandbox_locals = {}
    try:
        with contextlib.redirect_stdout(stdout):
            exec(code, sandbox_globals, sandbox_locals)
        result = sandbox_locals.get("result", sandbox_globals.get("result"))

        def _default(o):
            if isinstance(o, (pd.Series, pd.Index)):
                return o.tolist()
            if isinstance(o, pd.DataFrame):
                return o.to_dict(orient="records")
            if isinstance(o, (np.integer,)):
                return int(o)
            if isinstance(o, (np.floating,)):
                return float(o)
            if isinstance(o, (np.ndarray,)):
                return o.tolist()
            return str(o)

        result_json = None
        if result is not None:
            try:
                result_json = json.loads(json.dumps(result, default=_default))
            except Exception:
                result_json = str(result)
        return {
            "stdout": stdout.getvalue()[-4000:],
            "result": result_json,
        }
    except Exception:
        return {
            "stdout": stdout.getvalue()[-2000:],
            "error": traceback.format_exc()[-2000:],
        }


TOOL_IMPLS = {
    "web_search": web_search,
    "data_gov_in_resource": data_gov_in_resource,
    "fetch_url": fetch_url,
    "python_exec": python_exec,
}