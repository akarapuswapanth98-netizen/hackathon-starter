import os
from functools import lru_cache

# Load .env if present (no hard dependency)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


class Settings:
    """Env-driven settings. Read per-instance so tests can override env + cache_clear."""

    def __init__(self) -> None:
        self.LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock").lower()
        self.LLM_MODEL: str = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
        self.LLM_API_KEY: str = os.getenv("LLM_API_KEY", "") or os.getenv("OPENAI_API_KEY", "") or os.getenv("GROQ_API_KEY", "") or os.getenv("GEMINI_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
        self.OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
        self.GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
        self.ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
        # Optional fallback model retried ONCE on HTTP 429 only (per-model limits are
        # separate on Groq, so a second model may succeed when the primary is capped).
        self.LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", "")
        self.RAG_ENABLED: bool = _get_bool("RAG_ENABLED", False) or _get_bool("ENABLE_RAG", False)
        self.RAG_PROVIDER: str = os.getenv("RAG_PROVIDER", "mock")
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", "")
        self.DATABASE_AUTO_CREATE: bool = _get_bool("DATABASE_AUTO_CREATE", True)
        self.APP_MODE: str = os.getenv("APP_MODE", "AUTO").upper()
        self.APP_ENV: str = os.getenv("APP_ENV", "development")
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")
        self.CORS_ORIGINS: list[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]
        try:
            self.API_TIMEOUT: int = int(os.getenv("API_TIMEOUT", "30"))
        except ValueError:
            self.API_TIMEOUT = 30
        self.ML_ENABLED: bool = _get_bool("ML_ENABLED", False)
        self.VISION_ENABLED: bool = _get_bool("VISION_ENABLED", False)
        try:
            self.RATE_LIMIT_PER_MIN: int = int(os.getenv("RATE_LIMIT_PER_MIN", "600"))
        except ValueError:
            self.RATE_LIMIT_PER_MIN = 600
        self.AUTH_ENABLED: bool = _get_bool("AUTH_ENABLED", False)
        self.JWT_SECRET: str = os.getenv("JWT_SECRET", "")
        self.JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
        try:
            self.JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
        except ValueError:
            self.JWT_EXPIRE_MINUTES = 30
        self.MAPS_PROVIDER: str = os.getenv("MAPS_PROVIDER", "haversine").lower()

    def is_live_mode(self) -> bool:
        """Check if running in LIVE mode."""
        if self.APP_MODE == "LIVE":
            return True
        if self.APP_MODE == "DEMO":
            return False
        # AUTO: live if real LLM key and DATABASE_URL set
        has_real_llm = self.LLM_PROVIDER != "mock" and bool(self.LLM_API_KEY)
        has_db = bool(self.DATABASE_URL)
        return has_real_llm and has_db

    def is_demo_mode(self) -> bool:
        """Check if running in DEMO mode."""
        if self.APP_MODE == "DEMO":
            return True
        if self.APP_MODE == "LIVE":
            return False
        # AUTO: demo if no real LLM key or no DB
        return not self.is_live_mode()

    def get_database_url(self) -> str:
        """Get effective database URL with SQLite fallback."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        # Default to SQLite in ./data
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
        os.makedirs(data_dir, exist_ok=True)
        return f"sqlite:///{os.path.join(data_dir, 'hackathon.db')}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
