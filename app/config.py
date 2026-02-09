# app/config.py
from dotenv import load_dotenv
import os

load_dotenv()

class Settings:
    XAI_API_KEY = os.getenv("XAI_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/ai_hub")
    API_PREFIX = "/api"
    VERSION = "v1"

settings = Settings()