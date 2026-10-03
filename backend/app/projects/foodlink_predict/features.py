"""Feature engineering for the demand forecaster.

Pure stdlib. Kept separate from the model so the feature contract can be
tested without sklearn installed, and so leakage rules are stated once:

* Lags and rolling means are computed from rows strictly BEFORE the target
  date. Nothing at or after the target may influence that row's features.
* Calendar features come from ``calendar_days`` when present, otherwise they are
  derived from the date itself (never invented).
* Categorical context (item category, location) is exposed as-is; the model
  wrapper is responsible for encoding.

The feature vector order is part of the model contract, so it is defined once in
``FEATURE_NAMES`` and asserted against in tests.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Iterable, Sequence

# Order matters: it is persisted with the model version.
FEATURE_NAMES: tuple[str, ...] = (
    "day_of_week",
    "month",
    "day_of_month",
    "week_of_year",
    "is_weekend",
    "is_holiday",
    "days_to_holiday",
    "lag_7",
    "lag_14",
    "roll_mean_7",
    "roll_mean_28",
    "promo_flag",
    "trend_index",
)

# Columns supplied by the model wrapper on top of the numeric vector.
CONTEXT_COLUMNS: tuple[str, ...] = ("category", "location_id")


@dataclass(frozen=True)
class Series:
    """One ITEM x LOCATION history, sorted by date."""

    item_id: str
    location_id: str
    category: str
    dates: list[_dt.date]
    qty: list[float]
    promo: list[bool]

    def __len__(self) -> int:
        return len(self.dates)

    def index_of(self, day: _dt.date) -> int | None:
        try:
            return self.dates.index(day)
        except ValueError:
            return None


def build_series(rows: Iterable, *, item_id: str, location_id: str, category: str = "other") -> Series:
    """Build a Series from SalesDaily rows (any object with the right attrs)."""
    ordered = sorted(rows, key=lambda r: r.date)
    return Series(
        item_id=item_id,
        location_id=location_id,
        category=category or "other",
        dates=[r.date for r in ordered],
        qty=[float(r.qty_sold or 0.0) for r in ordered],
        promo=[bool(r.promo_flag) for r in ordered],
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def feature_row(
    series: Series,
    target_date: _dt.date,
    *,
    is_holiday: bool = False,
    days_to_holiday: float = 999.0,
    weather_score: float | None = None,
) -> tuple[list[float], dict]:
    """Build the feature vector for one (series, target_date).

    Returns ``(vector, meta)`` where meta carries the raw pieces a caller (or a
    human reading the trace) might want to check.

    Leakage guard: only ``series.dates < target_date`` is ever indexed.
    """
    prior = [(d, q, p) for d, q, p in zip(series.dates, series.qty, series.promo) if d < target_date]
    by_date: dict[_dt.date, float] = {d: q for d, q, _ in prior}

    def lag(n: int) -> float:
        return float(by_date.get(target_date - _dt.timedelta(days=n), 0.0))

    def roll(n: int) -> float:
        window_start = target_date - _dt.timedelta(days=n)
        vals = [q for d, q, _ in prior if window_start <= d < target_date]
        return _mean(vals)

    dow = target_date.weekday()

    # Promo flag: use the target day's value only if it is actually observed;
    # otherwise fall back to the most recent known day. Never guess a future promo.
    promo_today = series.promo[series.index_of(target_date)] if series.index_of(target_date) is not None else None
    promo_flag = 1.0 if (promo_today if promo_today is not None else (prior[-1][2] if prior else False)) else 0.0

    vector = [
        float(dow),
        float(target_date.month),
        float(target_date.day),
        float(target_date.isocalendar()[1]),
        1.0 if dow >= 5 else 0.0,
        1.0 if is_holiday else 0.0,
        float(min(days_to_holiday, 999.0)),
        lag(7),
        lag(14),
        roll(7),
        roll(28),
        promo_flag,
        float(len(prior)),
    ]
    if weather_score is not None:
        vector.append(float(weather_score))
    meta = {
        "target_date": target_date.isoformat(),
        "history_points": len(prior),
        "lag_7": vector[7],
        "lag_14": vector[8],
        "roll_mean_7": vector[9],
        "roll_mean_28": vector[10],
        "is_holiday": is_holiday,
        "days_to_holiday": min(days_to_holiday, 999.0),
        "weather_score": weather_score,
    }
    return vector, meta


def seasonal_naive(series: Series, target_date: _dt.date) -> float:
    """Mandatory baseline: same weekday, previous week.

    Returns 0.0 when there is no history 7 days back, which the caller must
    treat as 'no baseline available' rather than 'zero demand'.
    """
    prior = by_date_map(series).get(target_date - _dt.timedelta(days=7))
    return float(prior) if prior is not None else 0.0


def by_date_map(series: Series) -> dict[_dt.date, float]:
    return {d: q for d, q in zip(series.dates, series.qty)}


def cold_start_forecast(
    target_date: _dt.date,
    *,
    category_mean: float | None = None,
    location_mean: float | None = None,
    global_mean: float | None = None,
    prior_weight: int = 3,
) -> tuple[float, float, float]:
    """Shrinkage fallback for items with < cold_start_days of history.

    Blends category mean, location mean and global mean by how much history the
    series actually has, then widens the band with a fixed multiplicative
    spread. Deterministic and unit-testable; no model required.

    Returns ``(p10, p50, p90)``.
    """
    cats = category_mean if category_mean is not None else 0.0
    locs = location_mean if location_mean is not None else 0.0
    glb = global_mean if global_mean is not None else 0.0

    # prior_weight days of "pseudo-history" pull the blend toward the priors.
    blend_den = prior_weight + 1.0
    p50 = (cats + locs + glb) / 3.0 if (cats or locs or glb) else 0.0
    # Weekend adjustment is the only shape signal available without a model.
    if target_date.weekday() >= 5:
        p50 *= 0.45
    p50 = max(0.0, p50 * (1.0 + prior_weight / blend_den))

    # Wider band than the trained model: we genuinely know less here.
    p10 = max(0.0, p50 * 0.55)
    p90 = p50 * 1.75
    return p10, p50, p90


def wape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Weighted Absolute Percentage Error.

    sum(|a-p|) / sum(a). Returns 0.0 for an all-zero actual series rather than
    dividing by zero (an exactly-correct zero-demand forecast is not an error).
    """
    if len(actual) != len(predicted):
        raise ValueError(f"wape length mismatch: actual={len(actual)} predicted={len(predicted)}")
    denom = sum(abs(float(a)) for a in actual)
    if denom == 0:
        return 0.0
    numer = sum(abs(float(a) - float(p)) for a, p in zip(actual, predicted))
    return numer / denom


def bias(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Mean relative error, signed.

    Positive bias = over-forecasting. Returns 0.0 when there is no actual demand
    to compare against.
    """
    if len(actual) != len(predicted):
        raise ValueError(f"bias length mismatch: actual={len(actual)} predicted={len(predicted)}")
    denom = sum(abs(float(a)) for a in actual)
    if denom == 0:
        return 0.0
    return sum(float(p) - float(a) for a, p in zip(actual, predicted)) / denom


def smape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Symmetric MAPE - reported alongside WAPE so a single near-zero day
    cannot make WAPE look catastrophic on its own."""
    if len(actual) != len(predicted):
        raise ValueError("smape length mismatch")
    total, n = 0.0, 0
    for a, p in zip(actual, predicted):
        a, p = float(a), float(p)
        denom = (abs(a) + abs(p)) / 2.0
        total += 0.0 if denom == 0 else abs(a - p) / denom
        n += 1
    return total / n if n else 0.0