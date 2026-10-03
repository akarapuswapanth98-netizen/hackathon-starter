"""Impact ledger.

Every number here is arithmetic over stored facts, executed by code. The LLM
never sees this module and can never contribute to it (rule: "Never allow the
LLM to calculate impact").

Conversions, all configurable, all surfaced in the API response so a UI can
print "based on X g/meal and Y kg CO2e/kg":

    kg_saved     = qty * unit_weight_kg
    meals        = kg_saved / KG_PER_MEAL
    money_saved  = qty * unit_cost
    co2e_kg      = kg_saved * EMISSION_FACTOR_CO2E

Action-type multipliers distinguish outcomes honestly: food donated to people is
counted at full diversion value, whereas compost/animal feed is recorded as
*waste* (kg handled) and must not be reported as meals provided.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Sequence

from app.projects.foodlink_predict.config import (
    ACTION_COMPOST,
    ACTION_DONATE,
    ACTION_TRANSFER,
    ImpactConfig,
    get_impact_config,
)
from app.projects.foodlink_predict.models import ImpactEvent
from app.projects.foodlink_predict.util import iso, utcnow

# How each action type is accounted for. `meals` is only credited where food
# actually reached people.
ACTION_SEMANTICS: dict[str, dict[str, Any]] = {
    ACTION_DONATE: {"diversion": 1.0, "counts_as_meals": True, "counts_as_money_saved": True, "label": "redistributed to people"},
    ACTION_TRANSFER: {"diversion": 1.0, "counts_as_meals": True, "counts_as_money_saved": True, "label": "moved to a site with demand"},
    "promotion": {"diversion": 1.0, "counts_as_meals": True, "counts_as_money_saved": True, "label": "sold before it spoiled"},
    "buy_prepare_less": {"diversion": 1.0, "counts_as_meals": True, "counts_as_money_saved": True, "label": "never prepared"},
    ACTION_COMPOST: {"diversion": 0.0, "counts_as_meals": False, "counts_as_money_saved": False, "label": "waste stream - handled, not rescued"},
}


@dataclass
class ImpactRecord:
    kg_saved: float
    meals: float
    money_saved: float
    co2e_kg: float
    action_type: str
    semantics: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "kg_saved": round(self.kg_saved, 3),
            "meals": round(self.meals, 2),
            "money_saved": round(self.money_saved, 2),
            "co2e_kg": round(self.co2e_kg, 3),
            "action_type": self.action_type,
            "accounting": self.semantics,
        }


def compute(
    *,
    action_type: str,
    qty: float,
    unit_weight_kg: float,
    unit_cost: float,
    config: ImpactConfig | None = None,
) -> ImpactRecord:
    """Deterministic impact for one action on one quantity."""
    cfg = config or get_impact_config()
    cfg.validate()
    semantics = ACTION_SEMANTICS.get(
        action_type,
        {"diversion": 0.0, "counts_as_meals": False, "counts_as_money_saved": False, "label": "unknown action type"},
    )
    q = max(0.0, float(qty))
    kg = q * max(0.0, float(unit_weight_kg))
    diverted = kg * float(semantics["diversion"])

    return ImpactRecord(
        kg_saved=round(diverted, 6),
        meals=round(diverted / cfg.kg_per_meal, 6) if semantics["counts_as_meals"] else 0.0,
        money_saved=round(q * float(unit_cost) * (1.0 if semantics["counts_as_money_saved"] else 0.0), 6),
        co2e_kg=round(diverted * cfg.co2e_kg_per_kg, 6),
        action_type=action_type,
        semantics=semantics,
    )


def record(
    sess,
    *,
    org_id: str,
    action_type: str,
    qty: float,
    unit_weight_kg: float,
    unit_cost: float,
    recommendation_id: str | None = None,
    location_id: str | None = None,
    detail: dict[str, Any] | None = None,
    config: ImpactConfig | None = None,
    recorded_at: _dt.datetime | None = None,
) -> ImpactEvent:
    """Persist one impact event."""
    cfg = config or get_impact_config()
    rec = compute(
        action_type=action_type,
        qty=qty,
        unit_weight_kg=unit_weight_kg,
        unit_cost=unit_cost,
        config=cfg,
    )
    event = ImpactEvent(
        org_id=org_id,
        recommendation_id=recommendation_id,
        location_id=location_id,
        kg_saved=rec.kg_saved,
        meals=rec.meals,
        money_saved=rec.money_saved,
        co2e_kg=rec.co2e_kg,
        action_type=action_type,
        recorded_at=recorded_at or utcnow(),
        detail={
            "qty": round(float(qty), 3),
            "unit_weight_kg": round(float(unit_weight_kg), 4),
            "unit_cost": round(float(unit_cost), 4),
            "emission_factor_co2e_per_kg": cfg.co2e_kg_per_kg,
            "kg_per_meal": cfg.kg_per_meal,
            "accounting": rec.semantics,
            "computed_by": "flp.impact.compute (deterministic)",
            **(detail or {}),
        },
    )
    sess.add(event)
    sess.flush()
    return event


def aggregate(
    events: Sequence[ImpactEvent],
    *,
    config: ImpactConfig | None = None,
) -> dict[str, Any]:
    """Roll up events by total, action type and location."""
    cfg = config or get_impact_config()
    totals = {"kg_saved": 0.0, "meals": 0.0, "money_saved": 0.0, "co2e_kg": 0.0}
    by_action: dict[str, dict[str, float]] = {}
    by_location: dict[str, dict[str, float]] = {}
    by_day: dict[str, dict[str, float]] = {}

    def _bucket(container: dict[str, dict[str, float]], key: str, ev: ImpactEvent) -> None:
        b = container.setdefault(key, {"kg_saved": 0.0, "meals": 0.0, "money_saved": 0.0, "co2e_kg": 0.0, "events": 0.0})
        for f in ("kg_saved", "meals", "money_saved", "co2e_kg"):
            b[f] += float(getattr(ev, f) or 0.0)
        b["events"] += 1

    for ev in events:
        for f in totals:
            totals[f] += float(getattr(ev, f) or 0.0)
        _bucket(by_action, ev.action_type, ev)
        _bucket(by_location, ev.location_id or "unassigned", ev)
        _bucket(by_day, (ev.recorded_at.date().isoformat() if ev.recorded_at else "unknown"), ev)

    def _round(d: dict[str, float]) -> dict[str, Any]:
        return {
            "kg_saved": round(d["kg_saved"], 3),
            "meals": round(d["meals"], 2),
            "money_saved": round(d["money_saved"], 2),
            "co2e_kg": round(d["co2e_kg"], 3),
            "events": int(d["events"]),
        }

    return {
        "totals": {k: round(v, 3) for k, v in totals.items()},
        "event_count": len(events),
        "by_action": {k: _round(v) for k, v in sorted(by_action.items())},
        "by_location": {k: _round(v) for k, v in sorted(by_location.items())},
        "by_day": {k: _round(v) for k, v in sorted(by_day.items())},
        "factors": {
            "emission_factor_co2e_per_kg": cfg.co2e_kg_per_kg,
            "kg_per_meal": cfg.kg_per_meal,
            "source": "EMISSION_FACTOR_CO2E / KG_PER_MEAL environment variables",
            "note": "Defaults are indicative planning factors, not certified lifecycle assessments.",
        },
        "accounting_rules": {k: v["label"] for k, v in ACTION_SEMANTICS.items()},
        "generated_at": iso(utcnow()),
    }


def false_alarm_stats(sess, org_id: str) -> dict[str, Any]:
    """Forecast listings that were later withdrawn vs the ones confirmed.

    This is the honesty metric from the PDF's section 12: a prediction product
    that hides its miss rate cannot be trusted.
    """
    from sqlalchemy import func, select

    from app.projects.foodlink_predict.models import SurplusListing

    rows = sess.execute(
        select(SurplusListing.status, func.count()).where(SurplusListing.org_id == org_id).group_by(SurplusListing.status)
    ).all()
    counts = {str(status): int(n) for status, n in rows}
    total = sum(counts.values())
    withdrawn = counts.get("withdrawn", 0)
    confirmed = counts.get("confirmed", 0)
    return {
        "listings_total": total,
        "by_status": counts,
        "confirmed": confirmed,
        "withdrawn": withdrawn,
        # Denominator is listings that actually reached a decision.
        "false_alarm_rate": round(withdrawn / (confirmed + withdrawn), 4) if (confirmed + withdrawn) else 0.0,
        "false_alarm_basis": "withdrawn / (confirmed + withdrawn)",
    }