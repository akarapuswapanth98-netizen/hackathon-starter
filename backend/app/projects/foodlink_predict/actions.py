"""Action ladder: deterministic constraints on what may be recommended.

Order is the food-recovery hierarchy - prevent first, redistribute to people
next, waste last:

    1. buy_prepare_less  future recurring over-supply (applies to the NEXT order)
    2. transfer         another site has demand and transport fits the window
    3. promotion        moderate risk, time remains, margin acceptable
    4. donate           high risk / rising urgency / promo cannot clear the stock
    5. compost          no longer fit for people; still logged in waste accounting

Nothing here consults an LLM. The agent may only *choose among* the actions this
module marks feasible; ``validators.py`` then re-checks the chosen action
independently. Two layers, because a bug in either must not be able to authorise
an unsafe donation.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from app.projects.foodlink_predict.config import (
    ACTION_BUY_PREPARE_LESS,
    ACTION_COMPOST,
    ACTION_DONATE,
    ACTION_LADDER,
    ACTION_PROMOTION,
    ACTION_TRANSFER,
    SafetyConfig,
    get_safety_config,
)
from app.projects.foodlink_predict.risk import RiskAssessment
from app.projects.foodlink_predict.util import hours_until, iso, utcnow


@dataclass
class ActionRule:
    """Thresholds for one rung of the ladder. All configurable, none inline."""

    promotion_min_risk: float = 0.25
    promotion_max_risk: float = 0.70
    promotion_min_lead_hours: float = 12.0
    promotion_min_margin_per_unit: float = 0.0
    max_discount_fraction: float = 0.5
    donate_min_risk: float = 0.55
    donate_max_urgency_hours: float = 12.0
    transfer_min_destination_deficit: float = 1.0
    recurring_over_supply_days: int = 3
    recurring_horizon_days: int = 7
    compost_max_urgency_hours: float = 0.0
    # Average inter-site transport speed. The starter's maps provider gives
    # great-circle distance only, so ETA = distance / this. Always labelled
    # 'estimated'; never presented as live routing.
    transport_kmh: float = 30.0

    def eta_minutes(self, km: float) -> float:
        speed = max(1.0, float(self.transport_kmh))
        return (float(km) / speed) * 60.0


# Module-level default used only by `_eta`; `plan_transfer` prefers rules.transport_kmh.
TRANSPORT_KMH = 30.0


@dataclass
class ActionCandidate:
    action: str
    rank: int
    allowed: bool
    reason: str
    quantity: float = 0.0
    deadline: _dt.datetime | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "rank": self.rank,
            "allowed": self.allowed,
            "reason": self.reason,
            "quantity": round(float(self.quantity), 3),
            "deadline": iso(self.deadline),
            "detail": self.detail,
        }


@dataclass
class TransferPlan:
    destination_id: str
    destination_name: str
    distance_km: float
    eta_minutes: float
    eta_source: str
    fits_window: bool
    reason: str
    qty: float
    deadline: _dt.datetime | None = None

    def to_dict(self) -> dict:
        return {
            "destination_id": self.destination_id,
            "destination_name": self.destination_name,
            "distance_km": round(self.distance_km, 3),
            "eta_minutes": round(self.eta_minutes, 1),
            "eta_source": self.eta_source,
            "fits_window": self.fits_window,
            "reason": self.reason,
            "qty": round(float(self.qty), 3),
            "deadline": iso(self.deadline),
        }


# --------------------------------------------------------------------------
# Promotion arithmetic
# --------------------------------------------------------------------------
def promotion_math(
    *,
    qty: float,
    unit_price: float,
    unit_cost: float,
    discount_fraction: float,
    rules: ActionRule,
) -> dict[str, float]:
    """Discount economics. Deterministic; the LLM only picks a fraction in [0,1]."""
    frac = max(0.0, min(float(discount_fraction), 1.0))
    capped = min(frac, rules.max_discount_fraction)
    revenue_at_discount = qty * unit_price * (1.0 - capped)
    margin_at_discount = revenue_at_discount - qty * unit_cost
    return {
        "discount_fraction": frac,
        "applied_discount_fraction": capped,
        "discount_was_capped": frac > rules.max_discount_fraction,
        "unit_price_after_discount": round(unit_price * (1.0 - capped), 4),
        "revenue_at_risk": round(revenue_at_discount, 2),
        "margin_at_discount": round(margin_at_discount, 2),
        "margin_per_unit": round(unit_price * (1.0 - capped) - unit_cost, 4),
        "full_price_revenue": round(qty * unit_price, 2),
        "full_price_margin": round(qty * (unit_price - unit_cost), 2),
    }


# --------------------------------------------------------------------------
# Transfer feasibility
# --------------------------------------------------------------------------
def plan_transfer(
    *,
    assessment: RiskAssessment,
    origin: Any,
    destinations: list[dict],
    deficit_by_location: dict[str, float],
    rules: ActionRule,
    now: _dt.datetime | None = None,
) -> list[TransferPlan]:
    """Evaluate every candidate destination using the toolkit's maps provider.

    A transfer is only feasible when BOTH hold:
      * the destination has real forecast headroom for the item
      * travel time leaves enough slack before donate_by

    ETA comes from ``app.maps.provider`` (haversine offline). It is labelled
    ``estimated`` in the response - never presented as a live routing result.
    """
    ref = now or utcnow()
    out: list[TransferPlan] = []
    for dest in destinations:
        dest_id = str(dest.get("id", ""))
        if not dest_id or dest_id == origin.id:
            continue
        deficit = float(deficit_by_location.get(dest_id, 0.0))
        qty = min(assessment.stock_qty, max(0.0, deficit))
        if qty <= 0:
            out.append(
                TransferPlan(dest_id, dest.get("name", dest_id), 0.0, 0.0, "none", False,
                             f"destination '{dest.get('name', dest_id)}' has no forecast headroom for this item", 0.0)
            )
            continue
        km, minutes, source = _eta(origin, dest, assessment.donate_by, ref, kmh=rules.transport_kmh)
        slack = hours_until(assessment.donate_by, now=ref) - (minutes / 60.0)
        fits = slack > 0
        reason = (
            f"transfer of {qty:.0f} units to {dest.get('name', dest_id)} fits: "
            f"{minutes:.0f} min travel leaves {slack:.1f}h before donate-by"
            if fits
            else f"travel time {minutes:.0f} min exceeds the {assessment.urgency_hours:.1f}h remaining safety window"
        )
        out.append(
            TransferPlan(
                destination_id=dest_id,
                destination_name=str(dest.get("name", dest_id)),
                distance_km=km,
                eta_minutes=minutes,
                eta_source=source,
                fits_window=fits,
                reason=reason,
                qty=qty if fits else 0.0,
                deadline=assessment.donate_by,
            )
        )
    out.sort(key=lambda p: (not p.fits_window, p.distance_km))
    return out


def _eta(origin: Any, dest: dict, donate_by: _dt.datetime | None, now: _dt.datetime, kmh: float = TRANSPORT_KMH) -> tuple[float, float, str]:
    """Distance + ETA for a transfer, using the toolkit's maps provider.

    The starter's MapsProvider exposes ``haversine_km`` only - there is no
    routing or ETA service. So the ETA here is ``distance / assumed_speed`` and is
    labelled ``estimated`` everywhere it surfaces. The speed comes from
    ``ActionRule.transport_kmh``, not a constant, because a van and a bicycle
    differ and an operator should be able to set it.

    Unknown/missing coordinates return infeasible rather than a fake ETA.
    """
    try:
        from app.maps.provider import get_provider

        o_lat, o_lng = _coords(origin)
        d_lat, d_lng = _coords(dest)
        km = float(get_provider("haversine").haversine_km(o_lat, o_lng, d_lat, d_lng))
        speed = max(1.0, float(kmh))
        minutes = (km / speed) * 60.0
        return km, minutes, "haversine+estimated"
    except Exception:
        # Unknown coordinates must not produce a fake ETA. No distance = no transfer.
        return float("inf"), float("inf"), "unavailable"


def _coords(obj: Any) -> tuple[float, float]:
    """Accept a dict or an object with lat/lng. Returns (lat, lng)."""
    if isinstance(obj, dict):
        lat = float(obj.get("lat") or 0.0)
        lng = float(obj.get("lng") or 0.0)
    else:
        lat = float(getattr(obj, "lat", 0.0) or 0.0)
        lng = float(getattr(obj, "lng", 0.0) or 0.0)
    if lat == 0.0 and lng == 0.0:
        # Null Island is not a canteen: refuse rather than compute a nonsense ETA.
        raise ValueError("location has no coordinates")
    return lat, lng


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------
def rank_actions(
    assessment: RiskAssessment,
    *,
    item: Any,
    origin: Any,
    destinations: list[dict] | None = None,
    deficit_by_location: dict[str, float] | None = None,
    recurring_unsold_days: int | None = None,
    safety: SafetyConfig | None = None,
    rules: ActionRule | None = None,
    now: _dt.datetime | None = None,
) -> list[ActionCandidate]:
    """Return the ordered ladder for one batch, with an allow/deny reason each.

    The list is always the full hierarchy in order, so the agent sees why an
    action was rejected instead of only seeing what survived.
    """
    safety = safety or get_safety_config()
    rules = rules or ActionRule()
    ref = now or utcnow()
    out: list[ActionCandidate] = []

    # 1. Buy / prepare less ---------------------------------------------
    recurring = (
        recurring_unsold_days
        if recurring_unsold_days is not None
        else int(assessment.detail.get("recurring_unsold_days", 0) or 0)
    )
    if recurring >= rules.recurring_over_supply_days:
        out.append(
            ActionCandidate(
                ACTION_BUY_PREPARE_LESS,
                1,
                True,
                f"forecast shows over-supply on {recurring} of the last {rules.recurring_horizon_days} days; reduce the next order/prep run",
                quantity=round(assessment.expected_unsold, 2),
                deadline=assessment.donate_by,
                detail={"recurring_unsold_days": recurring, "applies_to": "next order or prep run, not current stock"},
            )
        )
    else:
        out.append(
            ActionCandidate(
                ACTION_BUY_PREPARE_LESS,
                1,
                False,
                f"over-supply repeats on {recurring} day(s); needs {rules.recurring_over_supply_days} to justify changing future orders",
                quantity=0.0,
                detail={"recurring_unsold_days": recurring},
            )
        )

    # 2. Transfer stock ---------------------------------------------------
    transfers = plan_transfer(
        assessment=assessment,
        origin=origin,
        destinations=destinations or [],
        deficit_by_location=deficit_by_location or {},
        rules=rules,
        now=ref,
    )
    feasible = [t for t in transfers if t.fits_window and t.qty > 0]
    if feasible:
        best = feasible[0]
        out.append(
            ActionCandidate(
                ACTION_TRANSFER,
                2,
                True,
                f"move {best.qty:.0f} units to {best.destination_name} ({best.distance_km:.1f} km, ~{best.eta_minutes:.0f} min) before donate-by",
                quantity=best.qty,
                deadline=assessment.donate_by,
                detail={"best_plan": best.to_dict(), "options": [t.to_dict() for t in transfers]},
            )
        )
    else:
        why = transfers[0].reason if transfers else "no other location is available for this organization"
        out.append(
            ActionCandidate(ACTION_TRANSFER, 2, False, why, 0.0,
                            detail={"options": [t.to_dict() for t in transfers]})
        )

    # 3. Markdown promotion ----------------------------------------------
    promo_ok = (
        rules.promotion_min_risk <= assessment.risk < rules.promotion_max_risk
        and assessment.urgency_hours >= rules.promotion_min_lead_hours
        and assessment.expected_unsold > 0
    )
    margin_per_unit = float(getattr(item, "unit_price", 0.0) or 0.0) - float(getattr(item, "unit_cost", 0.0) or 0.0)
    if promo_ok and margin_per_unit < rules.promotion_min_margin_per_unit:
        promo_ok = False
        promo_reason = (
            f"margin is {margin_per_unit:.2f} per unit; a markdown cannot clear stock without losing money"
        )
    elif not promo_ok:
        if assessment.risk >= rules.promotion_max_risk:
            promo_reason = f"risk {assessment.risk:.2f} is at or above {rules.promotion_max_risk}; promotion will not clear the quantity in time"
        elif assessment.urgency_hours < rules.promotion_min_lead_hours:
            promo_reason = f"only {assessment.urgency_hours:.1f}h left before donate-by; a markdown needs at least {rules.promotion_min_lead_hours}h"
        else:
            promo_reason = f"risk {assessment.risk:.2f} is below the promotion band {rules.promotion_min_risk}-{rules.promotion_max_risk}"
    else:
        promo_reason = f"risk {assessment.risk:.2f} with {assessment.urgency_hours:.1f}h of runway and an acceptable margin"
    out.append(
        ActionCandidate(
            ACTION_PROMOTION,
            3,
            promo_ok,
            promo_reason,
            quantity=round(assessment.expected_unsold, 2) if promo_ok else 0.0,
            deadline=assessment.donate_by,
            detail={
                "margin_per_unit": round(margin_per_unit, 4),
                "suggested_discount_fraction": suggest_discount(assessment, rules),
                "band": [rules.promotion_min_risk, rules.promotion_max_risk],
            },
        )
    )

    # 4. Donate through FoodLink -----------------------------------------
    donate_ok = (
        assessment.safe_to_donate
        and assessment.stock_qty > 0
        and (assessment.risk >= rules.donate_min_risk or assessment.urgency_hours <= rules.donate_max_urgency_hours)
    )
    if not assessment.redistributable:
        donate_reason = f"food class '{assessment.food_class}' is not on the redistributable list; donation is blocked"
    elif assessment.stock_qty <= 0:
        donate_reason = "no stock on hand"
    elif assessment.urgency_hours <= 0:
        donate_reason = "donate-by has already passed; this batch can no longer be donated"
    elif assessment.status == "expired":
        donate_reason = "batch is past expiry"
    elif not donate_ok:
        donate_reason = (
            f"risk {assessment.risk:.2f} is below {rules.donate_min_risk} and there is more than "
            f"{rules.donate_max_urgency_hours}h before donate-by; recovery steps come first"
        )
    else:
        donate_reason = (
            f"risk {assessment.risk:.2f}"
            + (f" with only {assessment.urgency_hours:.1f}h to donate-by" if assessment.urgency_hours <= rules.donate_max_urgency_hours else "")
            + "; promotion cannot clear the stock safely"
        )
    out.append(
        ActionCandidate(
            ACTION_DONATE,
            4,
            donate_ok,
            donate_reason,
            quantity=round(assessment.stock_qty, 2) if donate_ok else 0.0,
            deadline=assessment.donate_by,
            detail={
                # Confidence that the surplus materialises == the waste-risk score.
                "confidence_hint": round(clamp01(assessment.risk), 3) if donate_ok else 0.0,
                "confidence_semantics": "P(surplus materialises) = waste risk; staff confirmation pins it to 1.0",
            },
        )
    )

    # 5. Compost / animal feed -------------------------------------------
    compost_ok = assessment.urgency_hours <= rules.compost_max_urgency_hours or assessment.status == "expired"
    out.append(
        ActionCandidate(
            ACTION_COMPOST,
            5,
            bool(compost_ok),
            (
                f"donate-by passed {abs(assessment.urgency_hours):.1f}h ago; food is no longer fit for people"
                if assessment.urgency_hours <= 0
                else "food is still within a safe window for people; do not divert to waste streams"
            ),
            quantity=round(assessment.stock_qty, 2) if compost_ok else 0.0,
            deadline=assessment.donate_by,
            detail={"accounting": "still recorded in the waste ledger"},
        )
    )

    assert [c.action for c in out] == list(ACTION_LADDER), "ladder order must match the recovery hierarchy"
    return out


def suggest_discount(assessment: RiskAssessment, rules: ActionRule) -> float:
    """Heuristic starting discount, proportional to urgency. Deterministic."""
    if assessment.urgency_hours <= 0:
        return rules.max_discount_fraction
    span = max(1.0, assessment.urgency_hours)
    pressure = max(0.0, min(1.0, 1.0 - (assessment.urgency_hours / (span + 48.0))))
    return round(min(rules.max_discount_fraction, 0.15 + 0.35 * pressure), 2)


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def allowed_actions(candidates: list[ActionCandidate]) -> list[str]:
    return [c.action for c in candidates if c.allowed]


def preferred(candidates: list[ActionCandidate]) -> str | None:
    """First allowed action in hierarchy order, or None."""
    for c in candidates:
        if c.allowed:
            return c.action
    return None