# DuckDuckGo web search tool for LLM tool-calling.

from __future__ import annotations

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current or recent information. ALWAYS use this for "
            "questions about prices, news, events, or data after January 2025."
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


def execute_web_search(query: str) -> str:
    """Run DuckDuckGo text search; return formatted lines or an error string."""
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "No search results found."
        return "\n".join(
            f"- {r['title']}: {r['body']} ({r['href']})" for r in results
        )
    except Exception as e:
        return f"Search error: {e}"
