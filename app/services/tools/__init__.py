# app/services/tools — non-HTTP tool definitions used by handlers.
from app.services.tools.web_search import WEB_SEARCH_TOOL, execute_web_search

__all__ = ["WEB_SEARCH_TOOL", "execute_web_search"]
