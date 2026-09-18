# DuckDuckGo web search tool for LLM tool-calling.

from __future__ import annotations

import asyncio
from typing import Optional

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current or recent information. Use for "
            "questions about prices, news, events, or data after January 2025. "
            "Do not use for pure coding, math, or general knowledge questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
            },
            "required": ["query"],
        },
    },
}

# DDGS can hang on network issues; never block chat forever.
DEFAULT_SEARCH_TIMEOUT_SEC = 18.0


def execute_web_search(query: str, *, max_results: int = 5) -> str:
    """Run DuckDuckGo text search; return formatted lines or an error string."""
    q = (query or "").strip()
    if not q:
        return "Search error: empty query"
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(q, max_results=max_results))
        if not results:
            return "No search results found."
        lines = []
        for r in results:
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            href = (r.get("href") or "").strip()
            lines.append(f"- {title}: {body} ({href})")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"


async def execute_web_search_async(
    query: str,
    *,
    timeout: Optional[float] = None,
) -> str:
    """Async wrapper with a hard timeout so chat streams cannot hang on search."""
    limit = DEFAULT_SEARCH_TIMEOUT_SEC if timeout is None else float(timeout)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(execute_web_search, query),
            timeout=limit,
        )
    except asyncio.TimeoutError:
        return (
            f"Search timed out after {int(limit)}s for query: {query!r}. "
            "Answer from general knowledge and note that live search was unavailable."
        )
    except Exception as e:
        return f"Search error: {e}"
