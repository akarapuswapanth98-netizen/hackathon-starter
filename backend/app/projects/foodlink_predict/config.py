"""Typed configuration for FoodLink Predict.

Two rules drive this module:

1. Every safety-relevant number (safe holding windows, pickup lead time, food
   class eligibility) is CONFIGURATION, never a literal buried in logic.
2. Nothing here reads or returns an API key. Only the toolkit's Settings does
   that, and only for its own purposes.

Safe windows
------------
``donate_by`` is NOT ``expires_at``. It is the earliest of the shelf-life limit
and the safe holding window for the food class, minus the pickup lead time
FoodLink needs. Defaults below are conservative *defaults*, and they are
labelled as such: an operator in a jurisdiction with different rules must
override them via SAFE_WINDOWS_JSON.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

# --- Food classes -----------------------------------------------------------
# These are the classes the PDF names. Any other class falls back to the most
# conservative (shortest) window so an unmapped class can never silently get a
# generous donate-by.
FOOD_CLASSES = ("cooked", "chilled", "packaged", "produce")

DEFAULT_SAFE_WINDOWS_HOURS: dict[str, float] = {
    # Cooked food: shortest window - no re-heating assumption is made for us.
    "cooked": 24.0,
    "chilled": 48.0,
    "produce": 72.0,
    "packaged": 168.0,
}

# Classes that may be offered to people for redistribution. Anything not listed
# is NOT redistributable, which makes compost/animal-feed the only legal action.
REDISTRIBUTABLE_CLASSES = frozenset({"cooked", "chilled", "produce", "packaged"})

STORAGE_MODES = ("hot", "chilled", "ambient", "frozen")

# --- Action ladder ----------------------------------------------------------
# Recovery hierarchy: prevent first, redistribute to people next, waste last.
ACTION_BUY_PREPARE_LESS = "buy_prepare_less"
ACTION_TRANSFER = "transfer"
ACTION_PROMOTION = "promotion"
ACTION_DONATE = "donate"
ACTION_COMPOST = "compost"

ACTION_LADDER: tuple[str, ...] = (
    ACTION_BUY_PREPARE_LESS,
    ACTION_TRANSFER,
    ACTION_PROMOTION,
    ACTION_DONATE,
    ACTION_COMPOST,
)

RECOMMENDATION_STATUSES = ("proposed", "accepted", "rejected", "done")

LISTING_STATUSES = ("forecast", "confirmed", "withdrawn")

LISTING_SOURCE = "waste-predictor"


@dataclass(frozen=True)
class SafetyConfig:
    """Safety gates. Injected everywhere so tests can supply hostile values."""

    safe_windows_hours: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SAFE_WINDOWS_HOURS))
    pickup_lead_time_hours: float = 6.0
    redistributable_classes: frozenset[str] = REDISTRIBUTABLE_CLASSES
    cold_start_days: int = 14

    def window_for(self, food_class: str) -> float:
        """Safe holding window in hours for a food class.

        Unknown class -> the minimum configured window. Deliberately pessimistic:
        an unmapped food class must never receive a generous donate-by.
        """
        key = (food_class or "").strip().lower()
        if key in self.safe_windows_hours:
            return float(self.safe_windows_hours[key])
        return float(min(self.safe_windows_hours.values()))

    def is_redistributable(self, food_class: str) -> bool:
        return (food_class or "").strip().lower() in self.redistributable_classes

    def validate(self) -> None:
        """Reject a safety config that could produce an unsafe donate-by.

        Raises ValueError rather than silently clamping: a misconfigured safety
        window is an operator error that must be loud.
        """
        if not self.safe_windows_hours:
            raise ValueError("safe_windows_hours must not be empty")
        for k, v in self.safe_windows_hours.items():
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ValueError(f"safe window for {k!r} must be numeric")
            if v <= 0:
                raise ValueError(f"safe window for {k!r} must be > 0 hours, got {v}")
        if self.pickup_lead_time_hours < 0:
            raise ValueError(f"pickup_lead_time_hours must be >= 0, got {self.pickup_lead_time_hours}")
        if self.cold_start_days < 0:
            raise ValueError(f"cold_start_days must be >= 0, got {self.cold_start_days}")


def _safe_windows_from_env(raw: str) -> dict[str, float]:
    if not raw or not raw.strip():
        return dict(DEFAULT_SAFE_WINDOWS_HOURS)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SAFE_WINDOWS_JSON is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("SAFE_WINDOWS_JSON must be a JSON object of {food_class: hours}")
    out: dict[str, float] = dict(DEFAULT_SAFE_WINDOWS_HOURS)
    for k, v in parsed.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"SAFE_WINDOWS_JSON[{k!r}] must be a number of hours")
        out[str(k).strip().lower()] = float(v)
    return out


@lru_cache(maxsize=1)
def get_safety_config() -> SafetyConfig:
    """Build the safety config from the toolkit Settings (cached like get_settings)."""
    s = get_settings()
    cfg = SafetyConfig(
        safe_windows_hours=_safe_windows_from_env(os.getenv("SAFE_WINDOWS_JSON", "") or s.SAFE_WINDOWS_JSON),
        pickup_lead_time_hours=float(getattr(s, "PICKUP_LEAD_TIME_HOURS", 6.0)),
        cold_start_days=int(getattr(s, "FORECAST_COLD_START_DAYS", 14)),
    )
    cfg.validate()
    return cfg


def reset_safety_config() -> None:
    """Test helper: drop the cache so env changes take effect."""
    get_safety_config.cache_clear()


@dataclass(frozen=True)
class ImpactConfig:
    """Emission + conversion factors. Configurable and always surfaced in output."""

    co2e_kg_per_kg: float = 2.5
    kg_per_meal: float = 0.35

    def validate(self) -> None:
        if self.co2e_kg_per_kg < 0:
            raise ValueError(f"EMISSION_FACTOR_CO2E must be >= 0, got {self.co2e_kg_per_kg}")
        if self.kg_per_meal <= 0:
            raise ValueError(f"KG_PER_MEAL must be > 0, got {self.kg_per_meal}")


@lru_cache(maxsize=1)
def get_impact_config() -> ImpactConfig:
    s = get_settings()
    cfg = ImpactConfig(
        co2e_kg_per_kg=float(getattr(s, "EMISSION_FACTOR_CO2E", 2.5)),
        kg_per_meal=float(getattr(s, "KG_PER_MEAL", 0.35)),
    )
    cfg.validate()
    return cfg


def reset_impact_config() -> None:
    get_impact_config.cache_clear()


@dataclass(frozen=True)
class FLPConfig:
    """Everything the request path needs, resolved once per call."""

    enabled: bool
    demo_mode: bool
    ml_provider: str
    forecast_model: str
    db_url: str
    adapter_mode: str
    foodlink_api_url: str
    foodlink_listing_path: str
    safety: SafetyConfig
    impact: ImpactConfig

    @property
    def is_demo(self) -> bool:
        return self.demo_mode


def default_db_url() -> str:
    """SQLite file owned by this project.

    Deliberately NOT DATABASE_URL: the starter's DATABASE_URL often points at a
    Postgres that may not exist, and this module must run fully offline.
    """
    env = os.getenv("FOODLINK_PREDICT_DB_URL", "") or getattr(get_settings(), "FOODLINK_PREDICT_DB_URL", "")
    if env.strip():
        return env.strip()
    root = Path(__file__).resolve().parents[3]  # backend/
    data_dir = root / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return f"sqlite:///{(data_dir / 'foodlink_predict.db').as_posix()}"


def get_flp_config() -> FLPConfig:
    s = get_settings()
    return FLPConfig(
        enabled=bool(getattr(s, "FOODLINK_PREDICT_ENABLED", True)),
        demo_mode=bool(getattr(s, "DEMO_MODE", True)),
        ml_provider=str(getattr(s, "ML_PROVIDER", "sklearn")),
        forecast_model=str(getattr(s, "FORECAST_MODEL", "gradient_boosting")),
        db_url=default_db_url(),
        adapter_mode=str(getattr(s, "FOODLINK_ADAPTER_MODE", "demo")),
        foodlink_api_url=str(getattr(s, "FOODLINK_API_URL", "")),
        foodlink_listing_path=str(getattr(s, "FOODLINK_LISTING_PATH", "")),
        safety=get_safety_config(),
        impact=get_impact_config(),
    )


def reset_all_caches() -> None:
    """Drop every FLP config cache. Called by tests after monkeypatching env."""
    reset_safety_config()
    reset_impact_config()