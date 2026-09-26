"""Deterministic matching math - pure functions, no I/O, no LLM.

Weighted multi-criteria score (weights normalized to sum 1.0):

    score(shelter) = w_distance*distance
                   + w_demand*demand
                   + w_urgency*urgency
                   + w_capacity*capacity
                   + w_compatibility*compatibility
                   + w_expiry*expiry_feasibility

Allocation is a two-pass greedy over the ranked list:
  pass 1 - give each shelter its FULL demand while it fits (fairness: no starving),
  pass 2 - spread the remainder partially across the rest.

Default weights put distance first (0.50) because surplus meals are perishable:
proximity dominates delivery time, emissions and spoilage risk.
"""
import math
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

EARTH_RADIUS_KM = 6371.0088
MAX_DISTANCE_KM = 10.0          # distance score floor: 0 at >= 10 km
TRAVEL_SPEED_KMH = 25.0         # city van speed for ETA/expiry feasibility
URGENCY_SCORES = {"high": 1.0, "medium": 0.6, "low": 0.3}
WEIGHT_KEYS = ("distance", "demand", "urgency", "capacity", "compatibility", "expiry")


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def shelter_demand(shelter: Mapping) -> int:
    return max(0, int(shelter.get("capacity", 0)) - max(0, int(shelter.get("current_occupancy", 0))))


def normalize_weights(raw: Optional[Mapping[str, float]]) -> Dict[str, float]:
    """Scale arbitrary non-negative weights so they sum to 1.0; zeros -> uniform."""
    vals = {k: max(0.0, float((raw or {}).get(k, 0.0))) for k in WEIGHT_KEYS}
    total = sum(vals.values())
    if total <= 0:
        return {k: 1.0 / len(WEIGHT_KEYS) for k in WEIGHT_KEYS}
    return {k: v / total for k, v in vals.items()}


def distance_score(km: float, max_km: float = MAX_DISTANCE_KM) -> float:
    if max_km <= 0:
        return 0.0
    return _clamp01(1.0 - km / max_km)


def demand_score(demand: int, max_demand: int) -> float:
    if max_demand <= 0:
        return 0.0
    return _clamp01(demand / max_demand)


def urgency_score(level: str) -> float:
    return URGENCY_SCORES.get(str(level or "").lower(), 0.5)


def capacity_score(capacity: int, max_capacity: int) -> float:
    if max_capacity <= 0:
        return 0.0
    return _clamp01(capacity / max_capacity)


def compatibility_score(food_types: Sequence[str], requirements: Sequence[str]) -> float:
    reqs = [str(r).lower() for r in (requirements or [])]
    if not reqs:
        return 1.0                      # no dietary requirement -> fully compatible
    have = {str(t).lower() for t in (food_types or [])}
    return _clamp01(sum(1 for r in reqs if r in have) / len(reqs))


def expiry_score(hours_remaining: float, distance_km: float) -> float:
    """Travel feasibility: 1.0 when the van reaches well within the expiry window."""
    if hours_remaining <= 0:
        return 0.0
    travel_hours = distance_km / TRAVEL_SPEED_KMH
    return _clamp01(1.0 - travel_hours / hours_remaining)


def score_shelter(
    restaurant: Mapping,
    lot: Mapping,
    shelter: Mapping,
    weights: Mapping[str, float],
    *,
    max_demand: int,
    max_capacity: int,
    hours_remaining: float,
) -> Dict:
    km = haversine_km(restaurant["lat"], restaurant["lon"], shelter["lat"], shelter["lon"])
    demand = shelter_demand(shelter)
    components = {
        "distance": distance_score(km),
        "demand": demand_score(demand, max_demand),
        "urgency": urgency_score(shelter.get("urgency")),
        "capacity": capacity_score(shelter.get("capacity"), max_capacity),
        "compatibility": compatibility_score(lot.get("dietary_tags"), shelter.get("food_requirements")),
        "expiry": expiry_score(hours_remaining, km),
    }
    breakdown = {
        k: {
            "score": round(components[k], 4),
            "weight": round(float(weights[k]), 4),
            "weighted": round(components[k] * float(weights[k]), 4),
        }
        for k in WEIGHT_KEYS
    }
    total = sum(components[k] * float(weights[k]) for k in WEIGHT_KEYS)
    return {
        "shelter_id": shelter["id"],
        "shelter_name": shelter.get("name", shelter["id"]),
        "distance_km": round(km, 2),
        "demand": demand,
        "urgency": shelter.get("urgency"),
        "capacity": shelter.get("capacity"),
        "breakdown": breakdown,
        "score": round(total, 4),
    }


def score_all(
    restaurant: Mapping,
    lot: Mapping,
    shelters: Iterable[Mapping],
    weights: Mapping[str, float],
    *,
    hours_remaining: float,
    exclude: Optional[Iterable[str]] = None,
) -> List[Dict]:
    """Score and rank candidate shelters: best score first, id asc on ties."""
    excluded = set(exclude or ())
    candidates = [s for s in shelters if s.get("id") not in excluded and shelter_demand(s) > 0]
    max_demand = max((shelter_demand(s) for s in candidates), default=0)
    max_capacity = max((int(s.get("capacity", 0)) for s in candidates), default=0)
    entries = [
        score_shelter(
            restaurant, lot, s, weights,
            max_demand=max_demand, max_capacity=max_capacity, hours_remaining=hours_remaining,
        )
        for s in candidates
    ]
    entries.sort(key=lambda e: (-e["score"], e["shelter_id"]))
    return entries


def allocate_two_pass(
    meal_count: int,
    ranked: Sequence[Mapping],
    max_shelters: Optional[int] = None,
) -> Tuple[List[Dict], int]:
    """Two-pass greedy allocation. Returns (allocations, unallocated_meals)."""
    remaining = max(0, int(meal_count))
    chosen: List[Tuple[Mapping, int]] = []

    def cap_ok() -> bool:
        return max_shelters is None or len(chosen) < max_shelters

    # Pass 1: full demand only - a shelter gets everything it needs if we can afford it.
    for entry in ranked:
        if remaining <= 0 or not cap_ok():
            break
        need = int(entry.get("demand", 0))
        if 0 < need <= remaining:
            chosen.append((entry, need))
            remaining -= need

    # Pass 2: spread leftovers partially across remaining shelters.
    picked = {entry["shelter_id"] for entry, _ in chosen}
    for entry in ranked:
        if remaining <= 0 or not cap_ok():
            break
        if entry["shelter_id"] in picked:
            continue
        need = int(entry.get("demand", 0))
        if need <= 0:
            continue
        take = min(need, remaining)
        chosen.append((entry, take))
        remaining -= take

    allocations = [
        {
            "shelter_id": entry["shelter_id"],
            "shelter_name": entry["shelter_name"],
            "meals": meals,
            "distance_km": entry["distance_km"],
            "score": entry["score"],
            "breakdown": entry["breakdown"],
        }
        for entry, meals in chosen
    ]
    return allocations, remaining
