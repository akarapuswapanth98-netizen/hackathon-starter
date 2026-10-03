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

        # --- FoodLink Predict (project module; additive, defaults = safe/offline) ---
        # See app/projects/foodlink_predict/config.py for the typed accessors.
        self.FOODLINK_PREDICT_ENABLED: bool = _get_bool("FOODLINK_PREDICT_ENABLED", True)
        self.DEMO_MODE: bool = _get_bool("DEMO_MODE", True)
        self.ML_PROVIDER: str = os.getenv("ML_PROVIDER", "sklearn").lower()
        self.FORECAST_MODEL: str = os.getenv("FORECAST_MODEL", "gradient_boosting").lower()
        # FLP owns its own SQLite file by default so it never disturbs DATABASE_URL.
        self.FOODLINK_PREDICT_DB_URL: str = os.getenv("FOODLINK_PREDICT_DB_URL", "")
        # FoodLink adapter: "demo" (offline, clearly labelled) | "http" (needs contract)
        self.FOODLINK_ADAPTER_MODE: str = os.getenv("FOODLINK_ADAPTER_MODE", "demo").lower()
        self.FOODLINK_API_URL: str = os.getenv("FOODLINK_API_URL", "")
        # Path on FoodLink that accepts a surplus listing. Left empty on purpose:
        # the real FoodLink listing schema is UNVERIFIED, so we refuse to guess it.
        self.FOODLINK_LISTING_PATH: str = os.getenv("FOODLINK_LISTING_PATH", "")
        # kg CO2e avoided per kg of food diverted from landfill (WRAP/EPA-style default).
        try:
            self.EMISSION_FACTOR_CO2E: float = float(os.getenv("EMISSION_FACTOR_CO2E", "2.5"))
        except ValueError:
            self.EMISSION_FACTOR_CO2E = 2.5
        # Grams of food per meal-equivalent, for the impact ledger.
        try:
            self.KG_PER_MEAL: float = float(os.getenv("KG_PER_MEAL", "0.35"))
        except ValueError:
            self.KG_PER_MEAL = 0.35
        # Hours FoodLink needs to collect a confirmed listing.
        try:
            self.PICKUP_LEAD_TIME_HOURS: float = float(os.getenv("PICKUP_LEAD_TIME_HOURS", "6"))
        except ValueError:
            self.PICKUP_LEAD_TIME_HOURS = 6.0
        # JSON override for safe holding windows, e.g. {"cooked":24,"produce":72}
        self.SAFE_WINDOWS_JSON: str = os.getenv("SAFE_WINDOWS_JSON", "")
        # Minimum days of history before the ML model is trusted (below = cold start).
        try:
            self.FORECAST_COLD_START_DAYS: int = int(os.getenv("FORECAST_COLD_START_DAYS", "14"))
        except ValueError:
            self.FORECAST_COLD_START_DAYS = 14

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
