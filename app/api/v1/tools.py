# app/api/v1/tools.py
# Purpose: Centralized tool definitions and execution
#          - Keeps chat.py focused on routing
#          - Easy to add future tools (file upload, etc.)
#          - Uses duckduckgo-search for free web search

from ddgs import DDGS
import json

# Web search tool definition (for OpenAI/Grok tool calling)
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current or recent information. ALWAYS use this for questions about prices, news, events, or data after January 2025.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"]
        }
    }
}

def execute_web_search(query: str) -> str:
    """Execute DuckDuckGo search and return formatted results using new ddgs package.
    
    Args:
        query: Search query string
        
    Returns:
        Formatted string with top results
    """
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "No search results found."
            
        formatted = "\n".join([
            f"- {r['title']}: {r['body']} ({r['href']})" 
            for r in results
        ])
        return formatted
    except Exception as e:
        return f"Search error: {str(e)}"