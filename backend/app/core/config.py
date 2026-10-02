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

    # Database - SQLite default, PostgreSQL-ready
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    # Auto-create SQLite data directory
    DATABASE_AUTO_CREATE: bool = _get_bool("DATABASE_AUTO_CREATE", True)

    # Storage provider: memory | sqlalchemy
    STORAGE_PROVIDER: str = os.getenv("STORAGE_PROVIDER", "memory").lower()

    # Mode: LIVE | DEMO | AUTO
    # LIVE: real LLM, real DB, full features
    # DEMO: deterministic, in-memory, no tokens, demo reset
    # AUTO: detect from LLM_API_KEY and DATABASE_URL
    APP_MODE: str = os.getenv("APP_MODE", "AUTO").upper()

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

    # Optional features
    RAG_ENABLED: bool = _get_bool("RAG_ENABLED", False) or _get_bool("ENABLE_RAG", False)
    RAG_PROVIDER: str = os.getenv("RAG_PROVIDER", "mock")
    ML_ENABLED: bool = _get_bool("ML_ENABLED", False)
    VISION_ENABLED: bool = _get_bool("VISION_ENABLED", False)

    # Auth (optional)
    AUTH_ENABLED: bool = _get_bool("AUTH_ENABLED", False)
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))

    # Maps provider: haversine | osrm | google | mapbox
    MAPS_PROVIDER: str = os.getenv("MAPS_PROVIDER", "haversine").lower()

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

    def get_storage_provider(self) -> str:
        """Get effective storage provider."""
        if self.STORAGE_PROVIDER in ("memory", "sqlalchemy"):
            return self.STORAGE_PROVIDER
        # Auto: sqlalchemy in LIVE, memory in DEMO
        return "sqlalchemy" if self.is_live_mode() else "memory"


@lru_cache
def get_settings() -> Settings:
    return Settings()