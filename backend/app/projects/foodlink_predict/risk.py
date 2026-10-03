"""Waste-risk engine. Deterministic Python only - no LLM, no model calls.

The PDF's section 4.2 formulas, implemented literally and unit-tested:

    expected_demand  = sum of forecast demand from now until expiry (P10/P50/P90)
    expected_unsold  = max(0, stock - expected_demand)
    risk             = probability that demand until expiry is below stock
    urgency          = hours until the last safe donate-by time
    priority         = risk x value_at_risk, tie-broken by urgency

Two deliberate modelling choices, both documented in docs/ML.md:

1. **Multi-day spread.** Summing per-day quantiles understates uncertainty,
   because day-to-day errors do not perfectly cancel. Each day's implied sigma is
   derived from its own P10..P90 span and combined as sqrt(sum sigma^2) under an
   independent-days assumption. That is the standard, and it is deterministic.

2. **donate_by != expires_at.** donate_by is the earliest of the shelf-life limit
   and the food class's safe holding window, minus the pickup lead time FoodLink
   needs. It comes from configuration (``SafetyConfig``), never a literal here.

A batch that is already past its donate-by can never be donated; the engine marks
it so and the validator enforces it independently.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.projects.foodlink_predict.config import SafetyConfig, get_safety_config
from app.projects.foodlink_predict.util import as_utc, clamp, hours_until, iso, utcnow

# P10..P90 spans 2 * 1.2816 sigma for a normal distribution.
SIGMA_SPAN = 2.5632

# Floor on a day's relative sigma. Without it a perfectly smooth forecast would
# imply certainty and every batch would look either 0% or 100% risk.
MIN_RELATIVE_SIGMA = 0.05


@dataclass
class RiskInput:
    """Everything the engine needs, already resolved by the service layer."""

    batch_id: str
    org_id: str
    item_id: str
    location_id: str
    item_name: str
    food_class: str
    unit_cost: float
    qty: float
    prepared_at: _dt.datetime
    expires_at: _dt.datetime
    storage: str
    forecast: list[dict]  # [{'target_date': date, 'p10','p50','p90'}, ...] sorted
    model_version: str = "unknown"
    history_points: int = 0
    method: str = "model"


@dataclass
class RiskAssessment:
    batch_id: str
    item_id: str
    location_id: str
    item_name: str
    food_class: str
    computed_at: _dt.datetime
    stock_qty: float
    expected_demand: dict[str, float]  # {'p10':..,'p50':..,'p90':..}
    expected_unsold: float
    risk: float
    urgency_hours: float
    donate_by: _dt.datetime | None
    priority: float
    value_at_risk: float
    status: str  # expired | critical | high | moderate | low
    safe_to_donate: bool
    redistributable: bool
    horizon_days: int
    insufficient_history: bool
    model_version: str
    # Sigma of the aggregated multi-day demand. Kept as a field (not only in
    # detail) so a residual re-assessment can reuse it exactly.
    demand_sigma: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "item_id": self.item_id,
            "item_name": self.item_name,
            "location_id": self.location_id,
            "food_class": self.food_class,
            "computed_at": iso(self.computed_at),
            "stock_qty": round(self.stock_qty, 3),
            "expected_demand": {k: round(v, 3) for k, v in self.expected_demand.items()},
            "expected_unsold": round(self.expected_unsold, 3),
            "risk": round(self.risk, 4),
            "urgency_hours": round(self.urgency_hours, 2),
            "donate_by": iso(self.donate_by),
            "priority": round(self.priority, 4),
            "value_at_risk": round(self.value_at_risk, 2),
            "status": self.status,
            "safe_to_donate": self.safe_to_donate,
            "redistributable": self.redistributable,
            "horizon_days": self.horizon_days,
            "insufficient_history": self.insufficient_history,
            "model_version": self.model_version,
            "demand_sigma": round(self.demand_sigma, 4),
            "detail": self.detail,
        }


def assess_residual(
    assessment: RiskAssessment,
    remaining_qty: float,
    *,
    now: _dt.datetime | None = None,
) -> RiskAssessment:
    """Re-score a batch for the stock LEFT after an earlier recovery step.

    This is what makes "promote first, donate the remainder" work. The forecast
    window, donate-by and urgency are unchanged - only the quantity on hand
    shrinks - so the demand distribution is identical and only the comparison
    against stock changes. Pure arithmetic, no re-forecasting.
    """
    ref = as_utc(now) or assessment.computed_at
    qty = max(0.0, min(float(remaining_qty), assessment.stock_qty))
    mu = float(assessment.expected_demand.get("p50", 0.0))
    sigma = float(assessment.demand_sigma)
    unsold = max(0.0, qty - mu)
    risk = probability_demand_below(qty, mu, sigma)
    unit_cost = float(assessment.detail.get("unit_cost", 0.0) or 0.0)
    value = unsold * unit_cost
    priority = risk * value
    expired = assessment.status == "expired"

    detail = dict(assessment.detail)
    detail.update(
        {
            "residual_from_qty": assessment.stock_qty,
            "residual_qty": qty,
            "stage": "residual",
        }
    )
    return RiskAssessment(
        batch_id=assessment.batch_id,
        item_id=assessment.item_id,
        location_id=assessment.location_id,
        item_name=assessment.item_name,
        food_class=assessment.food_class,
        computed_at=ref,
        stock_qty=qty,
        expected_demand=dict(assessment.expected_demand),
        expected_unsold=unsold,
        risk=risk,
        urgency_hours=assessment.urgency_hours,
        donate_by=assessment.donate_by,
        priority=priority,
        value_at_risk=value,
        status=risk_status(risk, assessment.urgency_hours, expired=expired),
        safe_to_donate=bool(assessment.safe_to_donate and qty > 0),
        redistributable=assessment.redistributable,
        horizon_days=assessment.horizon_days,
        insufficient_history=assessment.insufficient_history,
        model_version=assessment.model_version,
        demand_sigma=sigma,
        detail=detail,
    )


class InvalidSafetyWindow(ValueError):
    """Raised when configuration would produce an unsafe donate_by."""


# --------------------------------------------------------------------------
# Donate-by calculation
# --------------------------------------------------------------------------
def compute_donate_by(
    *,
    prepared_at: _dt.datetime,
    expires_at: _dt.datetime,
    food_class: str,
    safety: SafetyConfig | None = None,
    now: _dt.datetime | None = None,
) -> _dt.datetime:
    """Earliest safe redistribution deadline.

        shelf-life limit  = prepared_at + safe window for the food class
        safety limit      = min(expires_at, shelf-life limit)
        donate_by         = safety limit - FoodLink pickup lead time

    Raises InvalidSafetyWindow for a nonsensical configuration or an inverted
    window rather than returning a date that would license an unsafe donation.
    """
    safety = safety or get_safety_config()
    safety.validate()

    prepared = as_utc(prepared_at)
    expires = as_utc(expires_at)
    if prepared is None or expires is None:
        raise InvalidSafetyWindow("prepared_at and expires_at are required")
    if expires < prepared:
        raise InvalidSafetyWindow(
            f"expires_at ({iso(expires)}) precedes prepared_at ({iso(prepared)}); refusing to compute donate_by"
        )

    window_hours = safety.window_for(food_class)
    if window_hours <= 0:
        raise InvalidSafetyWindow(f"safe window for food class '{food_class}' must be > 0, got {window_hours}")
    if safety.pickup_lead_time_hours < 0:
        raise InvalidSafetyWindow(f"pickup_lead_time_hours must be >= 0, got {safety.pickup_lead_time_hours}")

    shelf_limit = prepared + _dt.timedelta(hours=window_hours)
    safety_limit = min(expires, shelf_limit)
    return safety_limit - _dt.timedelta(hours=safety.pickup_lead_time_hours)


# --------------------------------------------------------------------------
# Statistics helpers
# --------------------------------------------------------------------------
def normal_cdf(z: float) -> float:
    """Standard normal CDF via math.erf - exact enough and dependency-free."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def day_sigma(p10: float, p50: float, p90: float) -> float:
    """Per-day sigma implied by a P10..P90 span, with a relative floor."""
    span = max(0.0, float(p90) - float(p10))
    sigma = span / SIGMA_SPAN
    return max(sigma, abs(float(p50)) * MIN_RELATIVE_SIGMA)


def aggregate_demand(points: Sequence[dict]) -> dict[str, float]:
    """Sum a multi-day forecast into mean, sigma and the three quantiles.

    ``points`` must be daily forecast dicts with p10/p50/p90. Days already in
    the past relative to ``now_date`` are excluded by the caller.
    """
    if not points:
        return {"p10": 0.0, "p50": 0.0, "p90": 0.0, "sigma": 0.0, "days": 0}
    mu = sum(float(p.get("p50", 0.0)) for p in points)
    var = sum(day_sigma(float(p.get("p10", 0.0)), float(p.get("p50", 0.0)), float(p.get("p90", 0.0))) ** 2 for p in points)
    sigma = math.sqrt(var)
    return {
        "p10": max(0.0, mu - 1.2816 * sigma),
        "p50": max(0.0, mu),
        "p90": max(0.0, mu + 1.2816 * sigma),
        "sigma": sigma,
        "days": len(points),
    }


def probability_demand_below(stock: float, mu: float, sigma: float) -> float:
    """P(total demand < stock). Deterministic; no sampling.

    Clamped to [RISK_FLOOR, RISK_CEILING] rather than [0, 1]: a forecast is never
    proof, so reporting 0.99 rather than a hard 1.00 keeps the board honest and
    stops a saturated metric from flattening every batch into the same bucket.
    """
    if sigma <= 0:
        hard = 1.0 if stock > mu else 0.0
        return clamp(hard, RISK_FLOOR, RISK_CEILING)
    return clamp(normal_cdf((float(stock) - float(mu)) / float(sigma)), RISK_FLOOR, RISK_CEILING)


# Never claim certainty from a forecast.
RISK_FLOOR = 0.01
RISK_CEILING = 0.99


def risk_status(risk: float, urgency_hours: float, *, expired: bool) -> str:
    if expired:
        return "expired"
    if risk >= 0.75 or urgency_hours <= 6:
        return "critical"
    if risk >= 0.5:
        return "high"
    if risk >= 0.25:
        return "moderate"
    return "low"


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
def assess(
    inp: RiskInput,
    *,
    safety: SafetyConfig | None = None,
    now: _dt.datetime | None = None,
    cold_start_days: int | None = None,
) -> RiskAssessment:
    """Compute the risk profile for one batch."""
    safety = safety or get_safety_config()
    ref = as_utc(now) or utcnow()
    cs_days = cold_start_days if cold_start_days is not None else safety.cold_start_days

    donate_by = compute_donate_by(
        prepared_at=inp.prepared_at,
        expires_at=inp.expires_at,
        food_class=inp.food_class,
        safety=safety,
        now=ref,
    )

    # Demand accumulates from now until EXPIRY (people can still buy until then),
    # while donate_by is the deadline for redistribution. Different clocks on
    # purpose: clearing stock by sale and rescuing it are different problems.
    expiry_date = as_utc(inp.expires_at).date()  # type: ignore[union-attr]
    today = ref.date()
    usable = [
        p
        for p in inp.forecast
        if p.get("target_date") is not None and today <= p["target_date"] <= expiry_date
    ]
    usable.sort(key=lambda p: p["target_date"])

    agg = aggregate_demand(usable)
    stock = max(0.0, float(inp.qty))
    expected_unsold = max(0.0, stock - agg["p50"])
    risk = probability_demand_below(stock, agg["p50"], agg["sigma"])

    urgency = hours_until(donate_by, now=ref)
    value_at_risk = expected_unsold * float(inp.unit_cost or 0.0)
    priority = risk * value_at_risk

    expired = as_utc(inp.expires_at) <= ref  # type: ignore[operator]
    redistributable = safety.is_redistributable(inp.food_class)
    safe_to_donate = bool(redistributable and not expired and urgency > 0)

    return RiskAssessment(
        batch_id=inp.batch_id,
        item_id=inp.item_id,
        location_id=inp.location_id,
        item_name=inp.item_name,
        food_class=inp.food_class,
        computed_at=ref,
        stock_qty=stock,
        expected_demand={"p10": agg["p10"], "p50": agg["p50"], "p90": agg["p90"]},
        expected_unsold=expected_unsold,
        risk=risk,
        urgency_hours=urgency,
        donate_by=donate_by,
        priority=priority,
        value_at_risk=value_at_risk,
        status=risk_status(risk, urgency, expired=expired),
        safe_to_donate=safe_to_donate,
        redistributable=redistributable,
        horizon_days=agg["days"],
        insufficient_history=inp.history_points < cs_days,
        model_version=inp.model_version,
        demand_sigma=agg["sigma"],
        detail={
            "demand_sigma": round(agg["sigma"], 4),
            "sigma_span_constant": SIGMA_SPAN,
            "min_relative_sigma": MIN_RELATIVE_SIGMA,
            "forecast_days_used": agg["days"],
            "forecast_method": inp.method,
            "history_points": inp.history_points,
            "cold_start_days": cs_days,
            "safe_window_hours": safety.window_for(inp.food_class),
            "pickup_lead_time_hours": safety.pickup_lead_time_hours,
            "expires_at": iso(inp.expires_at),
            "prepared_at": iso(inp.prepared_at),
            "storage": inp.storage,
            "unit_cost": float(inp.unit_cost or 0.0),
        },
    )


def rank(assessments: Sequence[RiskAssessment]) -> list[RiskAssessment]:
    """Priority order: risk x value_at_risk descending, urgency as tie-break.

    The tie-break is explicit in the sort key rather than left to insertion
    order, so two batches with identical priority always surface the more urgent
    one first.
    """
    return sorted(
        assessments,
        key=lambda a: (-a.priority, a.urgency_hours, a.batch_id),
    )


def top_risk(assessments: Sequence[RiskAssessment], min_risk: float = 0.0, limit: int | None = None) -> list[RiskAssessment]:
    filtered = [a for a in rank(assessments) if a.risk >= float(min_risk)]
    return filtered[:limit] if limit else filtered