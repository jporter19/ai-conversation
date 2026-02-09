# app/config.py
from dotenv import load_dotenv
import os

load_dotenv()

class Settings:
    XAI_API_KEY = os.getenv("XAI_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    # OPENAI_API_KEY = "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"
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/ai_hub")
    API_PREFIX = "/api"
    VERSION = "v1"

settings = Settings()