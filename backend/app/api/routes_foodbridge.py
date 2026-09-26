"""FoodBridge API routes - approved contract under /api/foodbridge/*."""
import logging
import time
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import AppError
from app.foodbridge.events import get_event_store
from app.foodbridge.models import (
    AgentEvent,
    Allocation,
    CreateSurplusRequest,
    FoodSurplus,
    MatchRequest,
    MatchResponse,
    utcnow,
)
from app.foodbridge.scoring import normalize_weights
from app.foodbridge.store import get_store
from app.foodbridge.workflow import run_match_workflow

logger = logging.getLogger("hackathon.foodbridge.api")
router = APIRouter(prefix="/foodbridge")

_VALID_STATUSES = {"completed", "failed", "timeout"}


def _lot_conflict(code: str, message: str, lot: FoodSurplus) -> JSONResponse:
    """409 for consumed / in-flight lots (structured body, additive shape)."""
    return JSONResponse(
        status_code=409,
        content={
            "success": False,
            "error": {"code": code, "message": message, "surplus_id": lot.id},
        },
    )


@router.get("/restaurants")
async def list_restaurants():
    return {"restaurants": [r.model_dump(mode="json") for r in get_store().list_restaurants()]}


@router.get("/shelters")
async def list_shelters():
    return {"shelters": [s.model_dump(mode="json") for s in get_store().list_shelters()]}


@router.get("/surplus")
async def list_surplus(restaurant_id: Optional[str] = None, include_all: bool = False):
    """Available lots by default; consumed lots only with include_all=true."""
    store = get_store()
    lots = (store.list_surpluses(restaurant_id) if include_all
            else store.list_available_surpluses(restaurant_id))
    return {"surplus": [l.model_dump(mode="json") for l in lots]}


@router.post("/surplus", status_code=201)
async def create_surplus(req: CreateSurplusRequest):
    store = get_store()
    if store.get_restaurant(req.restaurant_id) is None:
        raise AppError("Restaurant not found", status_code=404, detail=f"restaurant_id={req.restaurant_id}")
    now = utcnow()
    lot = FoodSurplus(
        id=f"food-{uuid.uuid4().hex[:8]}",
        restaurant_id=req.restaurant_id,
        meal_count=req.meal_count,
        food_type=req.food_type,
        dietary_tags=req.dietary_tags,
        prepared_at=now,
        expires_at=now + timedelta(hours=req.expires_in_hours),
        temperature_c=req.temperature_c,
        notes=req.notes,
    )
    store.add_surplus(lot)
    logger.info("Created surplus %s (%s meals)", lot.id, lot.meal_count)
    return {"success": True, "surplus": lot.model_dump(mode="json")}


@router.post("/match", response_model=MatchResponse)
async def match(req: MatchRequest):
    """Run the six-agent match workflow. Logical failures return 200 + status=failed."""
    store = get_store()

    # Resolve surplus lot (unknown id -> 404 AppError per contract)
    if req.surplus_id:
        lot = store.get_surplus(req.surplus_id)
        if lot is None:
            raise AppError("Surplus lot not found", status_code=404, detail=f"surplus_id={req.surplus_id}")
    else:
        lot = store.latest_surplus()
        if lot is None:
            raise AppError("No surplus lots available", status_code=404,
                           detail="Create one via POST /api/foodbridge/surplus")
    restaurant = store.get_restaurant(lot.restaurant_id)
    if restaurant is None:
        raise AppError("Restaurant not found", status_code=404, detail=f"restaurant_id={lot.restaurant_id}")
    if req.shelter_ids:
        missing = [sid for sid in req.shelter_ids if store.get_shelter(sid) is None]
        if missing:
            raise AppError("Shelter(s) not found", status_code=404, detail=", ".join(missing))

    # --- surplus lifecycle guards: 409 before any workflow work ---------
    if lot.status != "available":
        return _lot_conflict("SURPLUS_ALREADY_ALLOCATED",
                             f"Surplus lot {lot.id} has already been allocated", lot)
    if not store.reserve_surplus(lot.id):
        # reserve() failed: either another match holds the claim, or the lot
        # was consumed in the same instant - re-read to pick the right code.
        current = store.get_surplus(lot.id) or lot
        if current.status == "available":
            return _lot_conflict("SURPLUS_IN_PROGRESS",
                                 f"Another match is already in progress for lot {lot.id}", current)
        return _lot_conflict("SURPLUS_ALREADY_ALLOCATED",
                             f"Surplus lot {lot.id} has already been allocated", current)

    try:
        workflow_id = uuid.uuid4().hex
        initial = {
            "workflow_id": workflow_id,
            "surplus": lot.model_dump(mode="json"),
            "restaurant": restaurant.model_dump(mode="json"),
            "shelters": [s.model_dump(mode="json") for s in store.list_shelters()],
            "shelter_ids": req.shelter_ids or None,
            "requested_radius_km": req.requested_radius_km,
            "options": req.options.model_dump(),
            "retry_count": 0,
            "events": [],
            "steps": [],
            "status": "running",
        }

        settings = get_settings()
        started = time.monotonic()
        state = await run_match_workflow(initial)
        duration_ms = round((time.monotonic() - started) * 1000, 1)

        raw_status = state.get("status", "failed")
        status = raw_status if raw_status in _VALID_STATUSES else "failed"
        allocations = [Allocation(**a) for a in (state.get("allocations") or [])]
        events = [AgentEvent(**e) for e in (state.get("events") or [])]

        refreshed = store.get_surplus(lot.id) or lot  # post-commit lot state
        return MatchResponse(
            success=status == "completed",
            workflow_id=workflow_id,
            workflow_status=status,
            allocation=allocations,
            agent_events=events,
            total_allocated=sum(a.meals for a in allocations),
            unallocated=int(state.get("unallocated") or 0),
            summary=state.get("summary", ""),
            summary_source=state.get("summary_source", "skipped"),
            retry_count=int(state.get("retry_count") or 0),
            metadata={
                "weights": normalize_weights(settings.matching_weights()),
                "demo_mode": settings.foodbridge_demo_mode(),
                "llm_provider": settings.LLM_PROVIDER,
                "requested_radius_km": req.requested_radius_km,
                "max_retries": settings.MATCH_MAX_RETRIES,
                "duration_ms": duration_ms,
                "logistics": state.get("logistics") or {},
                "surplus_status": refreshed.status,
                "surplus_remaining": refreshed.meal_count,
            },
            error=state.get("error"),
        )
    finally:
        store.release_surplus(lot.id)  # never leak a claim, even on crash/timeout


@router.get("/agents/events")
async def list_agent_events(
    workflow_id: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    events = get_event_store().list(workflow_id=workflow_id, agent=agent, limit=limit)
    return {"events": events}


@router.post("/demo/reset")
async def demo_reset():
    # demo-only: hackathon rehearsal convenience, not a production feature (no auth).
    store = get_store()
    store.reset()  # reseeds rest-001, 3 shelters, food-001/80/available; also clears _reserved claims
    get_event_store().clear()
    return {"success": True, "message": "Demo data reset"}
