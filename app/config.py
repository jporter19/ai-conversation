# app/config.py
from dotenv import load_dotenv
import os

load_dotenv()


class Settings:
    # Fallbacks from environment; runtime prefers app/data/secrets.json via settings_store
    XAI_API_KEY = os.getenv("XAI_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    MAGISTERIUM_API_KEY = os.getenv("MAGISTERIUM_API_KEY")
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/ai_hub")
    API_PREFIX = "/api"
    VERSION = "v1"


settings = Settings()


def resolve_api_key(key_name: str) -> str | None:
    """Resolve an API key from secrets store, then env Settings/env."""
    try:
        from app.services.settings_store import get_secret
        val = get_secret(key_name)
        if val:
            return val
    except Exception:
        pass
    return os.getenv(key_name) or getattr(settings, key_name, None)
