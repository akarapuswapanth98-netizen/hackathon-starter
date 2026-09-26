"""FoodBridge agents - the six LangGraph nodes plus terminal coordinator nodes.

Every node is a pure function returning a partial state update (except the
final coordinator, which may call the LLM for a natural-language summary).
Every node emits exactly one AgentEvent into the shared event bus.

Nodes: coordinator, restaurant, shelter, matching, logistics, verification
Terminals: coordinator_final (success), coordinator_error (structured failure)
Routers:   coordinator_router, restaurant_router, shelter_router, verification_router
"""
import inspect
import logging
from datetime import datetime, timezone
from typing import Optional

from app.core.config import get_settings
from app.foodbridge.events import get_event_store
from app.foodbridge.prompts import (
    COORDINATOR_SYSTEM,
    build_fallback_summary,
    build_summary_prompt,
    deterministic_error_summary,
    deterministic_summary,
)
from app.foodbridge.scoring import (
    allocate_two_pass,
    haversine_km,
    normalize_weights,
    score_all,
    shelter_demand,
)
from app.foodbridge.store import get_store

logger = logging.getLogger("hackathon.foodbridge")

REPAIR_CODES = {"INCOMPATIBLE", "OVER_DEMAND", "UNKNOWN_SHELTER", "NEGATIVE_MEALS"}


def _emit(state, agent: str, status: str, detail: str) -> dict:
    return get_event_store().emit(state.get("workflow_id") or "", agent, status, detail)


def _track(state, ev: dict, **updates) -> dict:
    events = list(state.get("events") or []) + [ev]
    steps = list(state.get("steps") or []) + [f"{ev['agent']}[{ev['status']}]: {ev['detail']}"]
    return {"events": events, "steps": steps, **updates}


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------- coordinator
def coordinator_node(state: dict) -> dict:
    """Validate the request has a surplus lot + restaurant before anything runs."""
    if state.get("surplus") and state.get("restaurant"):
        ev = _emit(state, "coordinator", "running", "workflow started")
        return _track(state, ev, status="running")
    detail = "blocked: no surplus lot resolved" if not state.get("surplus") else "blocked: restaurant not found"
    ev = _emit(state, "coordinator", "failed", detail)
    return _track(state, ev, status="failed")


def coordinator_router(state: dict) -> str:
    return "restaurant" if state.get("surplus") and state.get("restaurant") else "error"


# ----------------------------------------------------------------- restaurant
def restaurant_node(state: dict) -> dict:
    """Attach lot freshness (hours to expiry); reject invalid/expired surplus."""
    surplus = dict(state.get("surplus") or {})
    restaurant = state.get("restaurant") or {}
    now = datetime.now(timezone.utc)
    try:
        hours = (_parse_dt(surplus.get("expires_at")) - now).total_seconds() / 3600.0
    except Exception:
        hours = 0.0
    updates = {"hours_remaining": hours}
    if hours <= 0:
        updates["error"] = {
            "code": "SURPLUS_EXPIRED",
            "message": f"Surplus lot {surplus.get('id')} expired ({hours:.2f}h remaining)",
            "details": [],
        }
        ev = _emit(state, "restaurant", "failed", updates["error"]["message"])
        return _track(state, ev, **updates)
    ev = _emit(
        state, "restaurant", "completed",
        f"{restaurant.get('name', 'restaurant')} offers {surplus.get('meal_count', 0)} "
        f"{surplus.get('food_type', 'meals')} ({', '.join(surplus.get('dietary_tags') or []) or 'untyped'}), "
        f"expires in {hours:.1f}h",
    )
    return _track(state, ev, **updates)


def restaurant_router(state: dict) -> str:
    if state.get("error"):
        return "error"
    return "shelter" if state.get("shelters") else "error"


# -------------------------------------------------------------------- shelter
def shelter_node(state: dict) -> dict:
    """Filter candidates: explicit ids, radius, dietary compatibility, usable demand."""
    wanted = set(state.get("shelter_ids") or [])
    radius = float(state.get("requested_radius_km") or 10.0)
    restaurant = state.get("restaurant") or {}
    lot = state.get("surplus") or {}
    lot_tags = {str(t).lower() for t in (lot.get("dietary_tags") or [])}
    out_of_radius = incompatible = unusable = 0
    candidates = []
    for s in (state.get("shelters") or []):
        if wanted and s.get("id") not in wanted:
            continue
        km = haversine_km(
            restaurant.get("lat", 0.0), restaurant.get("lon", 0.0),
            s.get("lat", 0.0), s.get("lon", 0.0),
        )
        if km > radius:
            out_of_radius += 1
            continue
        reqs = {str(r).lower() for r in (s.get("food_requirements") or [])}
        if reqs and not reqs <= lot_tags:
            incompatible += 1
            continue
        if shelter_demand(s) <= 0:
            unusable += 1
            continue
        candidates.append(s)
    if candidates:
        ev = _emit(
            state, "shelter", "completed",
            f"{len(candidates)} candidate shelter(s) within {radius} km "
            f"(dropped: {out_of_radius} out-of-radius, {incompatible} incompatible, {unusable} unusable)",
        )
        return _track(state, ev, candidates=candidates)
    ev = _emit(state, "shelter", "failed",
               f"no usable candidates within {radius} km "
               f"(dropped: {out_of_radius} out-of-radius, {incompatible} incompatible, {unusable} unusable)")
    return _track(state, ev, candidates=[], status="failed")


def shelter_router(state: dict) -> str:
    return "matching" if state.get("candidates") else "error"


# ------------------------------------------------------------------- matching
def matching_node(state: dict) -> dict:
    """Score candidates (weighted) and allocate with the two-pass greedy.

    On a verification retry, shelters implicated by repairable issues are
    excluded so the second pass provably differs from the first.
    """
    settings = get_settings()
    weights = normalize_weights(settings.matching_weights())
    restaurant = state.get("restaurant") or {}
    surplus = state.get("surplus") or {}
    hours = float(state.get("hours_remaining") or 0.0)

    verification = state.get("verification") or {}
    excluded = set()
    if verification and not verification.get("passed", True):
        for issue in verification.get("issues") or []:
            if issue.get("code") in REPAIR_CODES and issue.get("shelter_id"):
                excluded.add(issue["shelter_id"])

    ranked = score_all(
        restaurant, surplus, state.get("candidates") or [], weights,
        hours_remaining=hours, exclude=excluded,
    )
    allocations, unallocated = allocate_two_pass(
        int(surplus.get("meal_count") or 0),
        ranked,
        (state.get("options") or {}).get("max_shelters"),
    )
    total = sum(int(a["meals"]) for a in allocations)
    detail = (
        f"scored {len(ranked)} shelter(s); allocated {total}/{surplus.get('meal_count', 0)} meals "
        f"to {len(allocations)} shelter(s); {unallocated} unallocated"
    )
    if excluded:
        detail += f"; excluded after verification: {sorted(excluded)}"
    ev = _emit(state, "matching", "completed", detail)
    return _track(state, ev, ranked=ranked, allocations=allocations, unallocated=unallocated)


# ------------------------------------------------------------------ logistics
def logistics_node(state: dict) -> dict:
    """Turn allocations into an ordered delivery route (nearest first)."""
    ordered = sorted(state.get("allocations") or [], key=lambda a: float(a.get("distance_km") or 0))
    batches = []
    total_km = 0.0
    for i, a in enumerate(ordered, start=1):
        km = float(a.get("distance_km") or 0.0)
        batches.append({
            "order": i,
            "shelter_id": a.get("shelter_id"),
            "shelter_name": a.get("shelter_name"),
            "meals": int(a.get("meals") or 0),
            "distance_km": km,
            "eta_minutes": round(km / 25.0 * 60, 1),
        })
        total_km += km
    logistics = {
        "vehicle": "foodbridge-van-1",
        "batches": batches,
        "stops": len(batches),
        "total_distance_km": round(total_km, 2),
    }
    ev = _emit(state, "logistics", "completed", f"{len(batches)} delivery stop(s), ~{logistics['total_distance_km']} km total")
    return _track(state, ev, logistics=logistics)


# ---------------------------------------------------------------- verification
def verification_node(state: dict) -> dict:
    """Validate the allocation against every hard constraint. Pure: no state mutation.

    Hard checks: expiry, unknown shelters, non-negative meals, per-shelter demand,
    dietary compatibility, total <= lot size.
    Failure grants one bounded retry (MATCH_MAX_RETRIES, default 1); the router
    sends it back to matching which repairs by excluding implicated shelters.
    """
    settings = get_settings()
    lot = state.get("surplus") or {}
    allocations = state.get("allocations") or []
    candidates = {s.get("id"): s for s in (state.get("candidates") or [])}
    meal_count = int(lot.get("meal_count") or 0)
    issues = []

    hours = state.get("hours_remaining")
    if hours is not None and float(hours) <= 0:
        issues.append({"code": "EXPIRED_SURPLUS", "shelter_id": None,
                       "message": f"surplus expired ({float(hours):.2f}h remaining)"})

    total = 0
    for a in allocations:
        sid = a.get("shelter_id")
        meals = int(a.get("meals") or 0)
        if meals < 0:
            issues.append({"code": "NEGATIVE_MEALS", "shelter_id": sid, "message": f"negative meals: {meals}"})
        shelter = candidates.get(sid)
        if shelter is None:
            issues.append({"code": "UNKNOWN_SHELTER", "shelter_id": sid, "message": "shelter not in candidate set"})
            continue
        demand = shelter_demand(shelter)
        if meals > demand:
            issues.append({"code": "OVER_DEMAND", "shelter_id": sid,
                           "message": f"allocated {meals} > demand {demand}"})
        reqs = [str(r).lower() for r in (shelter.get("food_requirements") or [])]
        food = [str(t).lower() for t in (lot.get("dietary_tags") or [])]
        if reqs and not all(r in food for r in reqs):
            issues.append({"code": "INCOMPATIBLE", "shelter_id": sid,
                           "message": f"requires {reqs}, lot provides {food}"})
        total += max(meals, 0)

    if total > meal_count:
        issues.append({"code": "OVER_TOTAL", "shelter_id": None,
                       "message": f"allocated {total} exceeds lot size {meal_count}"})

    passed = not issues
    retry_count = int(state.get("retry_count") or 0)
    grant = (not passed) and (retry_count < settings.MATCH_MAX_RETRIES)
    if grant:
        retry_count += 1

    if passed:
        detail = f"passed: {len(allocations)} allocation(s), {total}/{meal_count} meals within all constraints"
        status = "completed"
    else:
        codes = ", ".join(sorted({i["code"] for i in issues}))
        detail = f"failed: {codes}" + (" - granting retry to matching" if grant else " - bounded retries exhausted")
        status = "failed"
    ev = _emit(state, "verification", status, detail)
    return _track(
        state, ev,
        verification={"passed": passed, "issues": issues, "grant_retry": grant},
        retry_count=retry_count,
        total_allocated=total,  # authoritative verified total, read (not recomputed) by coordinator_final
    )


def verification_router(state: dict) -> str:
    v = state.get("verification") or {}
    if v.get("passed"):
        return "final"
    return "matching" if v.get("grant_retry") else "error"


# ------------------------------------------------------ terminal coordinators
async def coordinator_final_node(state: dict) -> dict:
    """Natural-language summary: real LLM when configured, labeled template otherwise.

    Also commits the verified allocation to the surplus lot (consume-on-match).
    """
    settings = get_settings()
    options = state.get("options") or {}

    # Consume-on-match: commit the VERIFIED total produced by verification_node
    # (state["total_allocated"]) - never recompute it here, so what was checked
    # is exactly what gets committed. Runs regardless of include_summary.
    total = int(state.get("total_allocated") or 0)
    lot = state.get("surplus") or {}
    surplus_id = str(lot.get("id") or "")
    status_before = str(lot.get("status") or "available")
    store = get_store()
    committed = store.commit_allocation(surplus_id, total)
    status_after = committed.status if committed is not None else status_before

    source = "skipped"
    summary = ""
    if options.get("include_summary", True):
        if settings.foodbridge_demo_mode():
            summary = deterministic_summary(state)
            source = "deterministic"
        else:
            try:
                from app.ai.llm_service import LLMService
                llm = LLMService()
                out = await llm.generate(
                    build_summary_prompt(state), system=COORDINATOR_SYSTEM,
                    temperature=0.4, max_tokens=500,
                )
                summary = (out or "").strip()
                if summary:
                    source = f"llm:{llm.provider}"
                else:
                    summary, source = build_fallback_summary(state), "llm-fallback:empty"
            except Exception as e:
                logger.warning("FoodBridge summary LLM fallback: %s", e)
                summary, source = build_fallback_summary(state), f"llm-fallback:{e.__class__.__name__}"
    if committed is None:
        lot_note = f"; lot {surplus_id}: not found" if surplus_id else ""
    elif status_after != status_before:
        lot_note = f"; lot {surplus_id}: {status_before} -> {status_after}"
    else:
        lot_note = f"; lot {surplus_id}: {committed.meal_count} meals remaining ({status_after})"
    ev = _emit(
        state, "coordinator", "completed",
        f"match completed: {total} meals allocated, {state.get('unallocated', 0)} unallocated{lot_note}",
    )
    return _track(state, ev, summary=summary, status="completed", summary_source=source)


def _infer_error(state: dict) -> dict:
    if state.get("error"):
        return state["error"]
    if not state.get("surplus"):
        return {"code": "MISSING_SURPLUS", "message": "No surplus lot provided", "details": []}
    if not state.get("restaurant"):
        return {"code": "RESTAURANT_NOT_FOUND", "message": "Restaurant for surplus lot not found", "details": []}
    if not state.get("shelters"):
        return {"code": "NO_SHELTERS", "message": "No shelters registered for matching", "details": []}
    if not state.get("candidates"):
        return {"code": "NO_MATCHING_SHELTERS", "message": "No candidate shelters after filtering", "details": []}
    v = state.get("verification")
    if v and not v.get("passed"):
        return {
            "code": "VERIFICATION_FAILED",
            "message": f"Allocation rejected by verification ({len(v.get('issues') or [])} issue(s))",
            "details": v.get("issues") or [],
        }
    return {"code": "MATCH_FAILED", "message": "Match workflow failed", "details": []}


def coordinator_error_node(state: dict) -> dict:
    """Terminal failure node: structured, machine-readable error + labeled summary."""
    error = _infer_error(state)
    ev = _emit(state, "coordinator", "failed", f"{error['code']}: {error['message']}")
    return _track(state, ev, status="failed", error=error,
                  summary=deterministic_error_summary(error, state), summary_source="deterministic")
