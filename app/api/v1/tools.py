# Backward-compatible re-export. Prefer app.services.tools.
from app.services.tools.web_search import WEB_SEARCH_TOOL, execute_web_search

__all__ = ["WEB_SEARCH_TOOL", "execute_web_search"]
