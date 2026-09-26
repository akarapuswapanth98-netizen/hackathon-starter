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
    # LLM - provider agnostic
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock").lower()
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "") or os.getenv("OPENAI_API_KEY", "") or os.getenv("GROQ_API_KEY", "") or os.getenv("GEMINI_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
    # Allows per-provider override without changing LLM_API_KEY
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # RAG - disabled by default
    RAG_ENABLED: bool = _get_bool("RAG_ENABLED", False) or _get_bool("ENABLE_RAG", False)
    RAG_PROVIDER: str = os.getenv("RAG_PROVIDER", "mock")

    # DB - disabled by default
    SUPABASE_ENABLED: bool = _get_bool("SUPABASE_ENABLED", False) or _get_bool("ENABLE_DB", False)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # App
    APP_ENV: str = os.getenv("APP_ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")
    CORS_ORIGINS: list[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]
    API_TIMEOUT: int = int(os.getenv("API_TIMEOUT", "30"))

    # FoodBridge - matching weights (normalized to sum 1.0 at runtime)
    MATCH_W_DISTANCE: float = float(os.getenv("MATCH_W_DISTANCE", "0.50"))
    MATCH_W_DEMAND: float = float(os.getenv("MATCH_W_DEMAND", "0.10"))
    MATCH_W_URGENCY: float = float(os.getenv("MATCH_W_URGENCY", "0.15"))
    MATCH_W_CAPACITY: float = float(os.getenv("MATCH_W_CAPACITY", "0.05"))
    MATCH_W_COMPATIBILITY: float = float(os.getenv("MATCH_W_COMPATIBILITY", "0.10"))
    MATCH_W_EXPIRY: float = float(os.getenv("MATCH_W_EXPIRY", "0.10"))
    MATCH_TIMEOUT_SECONDS: int = int(os.getenv("MATCH_TIMEOUT_SECONDS", "10"))
    MATCH_MAX_RETRIES: int = int(os.getenv("MATCH_MAX_RETRIES", "1"))
    # auto | true | false - "auto" = demo mode when no real LLM API key is configured
    FOODBRIDGE_DEMO_MODE: str = os.getenv("FOODBRIDGE_DEMO_MODE", "auto").strip().lower()

    def matching_weights(self) -> dict[str, float]:
        """Configured scoring weights (raw; normalize at use site)."""
        return {
            "distance": self.MATCH_W_DISTANCE,
            "demand": self.MATCH_W_DEMAND,
            "urgency": self.MATCH_W_URGENCY,
            "capacity": self.MATCH_W_CAPACITY,
            "compatibility": self.MATCH_W_COMPATIBILITY,
            "expiry": self.MATCH_W_EXPIRY,
        }

    def foodbridge_demo_mode(self) -> bool:
        """Resolve FOODBRIDGE_DEMO_MODE: explicit true/false, or auto (no real key -> demo)."""
        val = self.FOODBRIDGE_DEMO_MODE
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off"):
            return False
        # auto: real provider + api key available -> real LLM, otherwise demo
        return not (self.LLM_PROVIDER != "mock" and bool(self.LLM_API_KEY))


@lru_cache
def get_settings() -> Settings:
    return Settings()
