"""FoodLink Predict API.

Endpoints (PDF section 7):

    POST /api/ingest     NEW - CSV ingestion for sales/inventory/items/calendar
    POST /api/demo/seed  NEW - load the labelled synthetic demo dataset
    POST /api/forecast   NEW - fit/refresh P10/P50/P90 forecasts
    GET  /api/risk       NEW - ranked at-risk batches with donate-by
    POST /api/recommend  NEW - run the agent, return validated actions
    POST /api/surplus    NEW - create / confirm / withdraw / status a listing
    GET  /api/impact     NEW - aggregated impact
    GET  /api/health/flp NEW - module + adapter + safety config status

The toolkit's existing endpoints (/api/upload, /api/solve, /api/solve/stream,
/api/health) are untouched. /api/upload still accepts a CSV; this module adds the
domain normalisation on top rather than changing that route's contract.

Conventions borrowed from the starter: FastAPI router with a module-level
``router``, Pydantic request bodies, errors raised as ``AppError`` so the global
handler in app/core/errors.py produces the standard body, and ``X-Request-ID``
from the toolkit middleware for observability.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.projects.foodlink_predict import impact as I
from app.projects.foodlink_predict import service as S
from app.projects.foodlink_predict import surplus as SURPLUS
from app.projects.foodlink_predict.config import get_flp_config, get_safety_config
from app.projects.foodlink_predict.errors import ValidationFailed
from app.projects.foodlink_predict.ingest import ingest_any
from app.projects.foodlink_predict.schemas import (
    DemoSeedRequest,
    ForecastRequest,
    IngestBatchRequest,
    IngestRequest,
    RecommendRequest,
    RiskQuery,
    SurplusActionRequest,
    SurplusConfirmRequest,
    SurplusCreateRequest,
    SurplusWithdrawRequest,
)
from app.projects.foodlink_predict.tenancy import DEMO_ORG_ID, ensure_org_exists, resolve_org_id

logger = logging.getLogger("flp.api")

router = APIRouter()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _ctx(request: Request, org_id: str | None):
    """Resolve tenancy, reusing the toolkit's JWT when AUTH_ENABLED."""
    token = None
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    ctx = resolve_org_id(org_id, token=token)
    ensure_org_exists(ctx.org_id)
    return ctx


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "unknown")


def _envelope(data: dict, request: Request, **extra: Any) -> dict:
    """Consistent success shape.

    The starter's own routes return plain dicts; this envelope adds the request id
    and effective mode that the toolkit middleware already produces, without
    changing any existing route's contract.
    """
    from app.core.config import get_settings

    s = get_settings()
    mode = "live" if s.is_live_mode() else "demo"
    return {
        "success": True,
        "data": data,
        "meta": {
            "request_id": _request_id(request),
            "mode": mode,
            "app_version": "0.1.0",
            "module": "foodlink_predict",
            **extra,
        },
    }


# --------------------------------------------------------------------------
# ingestion
# --------------------------------------------------------------------------
@router.post("/ingest", summary="Ingest a sales / inventory / items / calendar CSV")
async def ingest(body: IngestRequest, request: Request):
    from app.projects.foodlink_predict.db import session_scope

    ctx = _ctx(request, body.org_id)
    with session_scope() as sess:
        report = ingest_any(sess, ctx.org_id, body.csv_text, kind=body.kind, source=body.source)
    payload = report.to_dict()
    if not payload["ok"]:
        # Row-level problems are returned in full rather than raising, so a
        # caller can fix the exact lines. Fatal problems still raise.
        fatal = [i for i in payload["issues"] if i["code"] in ("missing_columns", "unknown_kind")]
        if fatal:
            raise ValidationFailed(fatal[0]["message"], issues=payload["issues"])
    return _envelope(
        {
            "org_id": ctx.org_id,
            **payload,
            "synthetic_label": "SYNTHETIC rows are labelled source=synthetic and must be shown as demo data"
            if body.source == "synthetic"
            else None,
        },
        request,
    )


@router.post("/ingest/batch", summary="Ingest several CSVs in one call")
async def ingest_batch(body: IngestBatchRequest, request: Request):
    from app.projects.foodlink_predict.db import session_scope
    from app.projects.foodlink_predict.ingest import summarize_reports

    ctx = _ctx(request, body.files[0].org_id)
    reports = []
    with session_scope() as sess:
        for f in body.files:
            reports.append(ingest_any(sess, ctx.org_id, f.csv_text, kind=f.kind, source=f.source))
    return _envelope({"org_id": ctx.org_id, **summarize_reports(reports)}, request)


# --------------------------------------------------------------------------
# demo
# --------------------------------------------------------------------------
@router.post("/demo/seed", summary="Load the labelled synthetic demo dataset")
async def demo_seed(body: DemoSeedRequest, request: Request):
    from app.projects.foodlink_predict import synthetic
    from app.projects.foodlink_predict.db import session_scope
    from app.projects.foodlink_predict.models import (
        Batch,
        CalendarDay,
        Forecast,
        ImpactEvent,
        Item,
        Location,
        Recommendation,
        SalesDaily,
        SurplusListing,
        WasteRisk,
    )
    from app.projects.foodlink_predict.tenancy import DEMO_ORG_ID as _DEMO

    org_id = body.org_id or _DEMO
    ensure_org_exists(org_id, "Demo Cafeteria", org_type="demo")
    dataset = synthetic.generate(history_days=body.history_days, seed=body.seed)

    if body.reset:
        with session_scope() as sess:
            # Delete in dependency order; FLP tables only.
            for model in (ImpactEvent, SurplusListing, Recommendation, WasteRisk, Forecast, Batch, SalesDaily, CalendarDay, Item, Location):
                sess.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)

    with session_scope() as sess:
        summary = synthetic.load_into_db(sess, org_id, dataset)

    return _envelope(
        {
            "org_id": org_id,
            **summary,
            "next_steps": [
                "POST /api/forecast  (fits P10/P50/P90 + backtest)",
                "GET  /api/risk      (ranked risk board)",
                "POST /api/recommend (agent + validator)",
                "POST /api/surplus   (create -> confirm -> impact)",
                "POST /api/demo/scenario  (whole story in one call)",
            ],
        },
        request,
    )


# --------------------------------------------------------------------------
# forecast
# --------------------------------------------------------------------------
@router.post("/forecast", summary="Fit or refresh P10/P50/P90 demand forecasts")
async def forecast(body: ForecastRequest, request: Request):
    ctx = _ctx(request, body.org_id)
    result = S.run_forecast(
        ctx.org_id,
        location_id=body.location_id,
        horizon_days=body.horizon_days,
        include_backtest=body.include_backtest,
    )
    return _envelope(result, request)


@router.get("/forecast", summary="Read stored forecast rows")
async def forecast_get(
    request: Request,
    org_id: Optional[str] = Query(None),
    item_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    from app.projects.foodlink_predict.util import parse_date

    ctx = _ctx(request, org_id)
    try:
        rows = S.stored_forecast(
            ctx.org_id,
            item_id=item_id,
            location_id=location_id,
            start=parse_date(start, field="start") if start else None,
            end=parse_date(end, field="end") if end else None,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc))
    return _envelope(
        {
            "org_id": ctx.org_id,
            "count": len(rows),
            "rows": [
                {**r, "target_date": r["target_date"].isoformat()} for r in rows
            ],
        },
        request,
    )


# --------------------------------------------------------------------------
# risk
# --------------------------------------------------------------------------
@router.get("/risk", summary="Ranked at-risk batches with donate-by countdown")
async def risk(
    request: Request,
    org_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    min_risk: float = Query(0.0, ge=0.0, le=1.0),
    batch_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    recompute: bool = Query(True),
):
    ctx = _ctx(request, org_id)
    if recompute:
        assessments = S.compute_risk(
            ctx.org_id, batch_id=batch_id, location_id=location_id, persist=True
        )
    else:
        assessments = S.compute_risk(
            ctx.org_id, batch_id=batch_id, location_id=location_id, persist=False
        )
    from app.projects.foodlink_predict.risk import top_risk

    items = [a.to_dict() for a in top_risk(assessments, min_risk=min_risk, limit=limit)]
    safety = get_safety_config()
    return _envelope(
        {
            "org_id": ctx.org_id,
            "count": len(items),
            "items": items,
            "computed_at": items[0]["computed_at"] if items else None,
            "safety_config": {
                "safe_windows_hours": safety.safe_windows_hours,
                "pickup_lead_time_hours": safety.pickup_lead_time_hours,
                "redistributable_classes": sorted(safety.redistributable_classes),
                "note": "donate_by is the earliest of the shelf-life limit and the safe holding window, minus pickup lead time. It is never expires_at.",
            },
        },
        request,
    )


# --------------------------------------------------------------------------
# recommend
# --------------------------------------------------------------------------
@router.post("/recommend", summary="Run the recommendation agent with the hard validator")
async def recommend(body: RecommendRequest, request: Request):
    ctx = _ctx(request, body.org_id)
    result = await S.recommend(
        ctx.org_id,
        batch_id=body.batch_id,
        location_id=body.location_id,
        min_risk=body.min_risk,
        limit=body.limit,
        persist=body.persist,
    )
    return _envelope(result, request)


@router.post("/recommend/stream", summary="SSE: agent trace for a recommendation")
async def recommend_stream(body: RecommendRequest, request: Request):
    """Server-sent events for the recommendation agent.

    Reuses the starter's SSE conventions (StreamingResponse,
    ``data: {json}\\n\\n``, Cache-Control/X-Accel-Buffering headers) from
    routes_solve.solve_stream. Events are emitted as real work completes - there
    is no scripted progress ticker and no event is emitted for work that did not
    happen.
    """
    from app.projects.foodlink_predict import tools as T
    from app.projects.foodlink_predict.agent import new_state, run_recommendation

    ctx = _ctx(request, body.org_id)

    def _sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, default=str)}\n\n"

    async def gen():
        yield _sse({"type": "start", "org_id": ctx.org_id, "stage": "risk"})
        # Real stage 1: deterministic risk + ladder.
        assessments = S.compute_risk(ctx.org_id, location_id=body.location_id, persist=True)
        if not assessments:
            yield _sse({"type": "error", "code": "NO_BATCHES", "message": "No inventory batches to score for this organization"})
            return
        from app.projects.foodlink_predict.risk import top_risk

        targets = top_risk(assessments, min_risk=body.min_risk, limit=body.limit)
        yield _sse({"type": "risk", "stage": "waste risk computed", "count": len(assessments), "targets": len(targets)})
        ref = S.utcnow()

        org_token = T.set_org_context(ctx.org_id)
        final: dict = {}
        try:
            for assessment in targets:
                yield _sse({"type": "planner", "stage": "planning", "batch_id": assessment.batch_id, "item": assessment.item_name})
                from app.projects.foodlink_predict.config import get_safety_config as _gsc

                ladder = S.build_ladder(ctx.org_id, assessment, ref, _gsc())
                recovery = S.build_recovery_plan(ctx.org_id, assessment, ref, _gsc())
                yield _sse(
                    {
                        "type": "actions",
                        "stage": "evaluating actions",
                        "batch_id": assessment.batch_id,
                        "allowed": [s["action"] for s in recovery["plan"]],
                        "recovery_plan": recovery["plan"],
                        "ladder": [c.to_dict() for c in ladder],
                    }
                )
                bctx = {
                    "ladder": [c.to_dict() for c in ladder],
                    "risk": assessment.to_dict(),
                    "recovery_plan": recovery,
                    "item": S.item_payload(ctx.org_id, assessment.item_id),
                    "preferred_action": next((s["action"] for s in recovery["plan"]), None),
                    "allowed_actions": [s["action"] for s in recovery["plan"]],
                }
                btoken = T.set_batch_context(bctx)
                try:
                    state = new_state(ctx.org_id, assessment.batch_id)
                    state["evidence"] = {
                        "item_id": assessment.item_id,
                        "location_id": assessment.location_id,
                        "food_class": assessment.food_class,
                        "storage": assessment.detail.get("storage"),
                        "horizon_days": 7,
                        "risk": assessment.to_dict(),
                        "ladder": bctx["ladder"],
                        "recovery_plan": recovery,
                    }
                    final = await run_recommendation(state)
                finally:
                    T.reset_batch_context(btoken)

                for entry in final.get("trace", []):
                    yield _sse({"type": "step", "stage": entry.get("node"), "detail": entry})
                val = final.get("validation") or {}
                yield _sse(
                    {
                        "type": "validator",
                        "stage": "safety validation",
                        "batch_id": assessment.batch_id,
                        "passed": val.get("passed"),
                        "issues": val.get("issues", []),
                    }
                )
                if not val.get("passed") and final.get("retry_count"):
                    yield _sse({"type": "replan", "stage": "replanning after validator rejection", "batch_id": assessment.batch_id})

                proposal = final.get("proposal") or {}
                rec = S.persist_recommendation(
                    ctx.org_id,
                    assessment=assessment,
                    proposal=proposal,
                    validation=val or {},
                    trace=final.get("tool_calls", []),
                    ref=ref,
                    persist=body.persist,
                    llm_used=bool(final.get("llm_used")),
                )
                yield _sse(
                    {
                        "type": "recommendation",
                        "stage": "recommendation ready",
                        "batch_id": assessment.batch_id,
                        "action": proposal.get("action"),
                        "quantity": proposal.get("quantity"),
                        "deadline": proposal.get("deadline"),
                        "rationale": proposal.get("rationale"),
                        "validation_status": rec["validation_status"],
                        "recommendation_id": rec["id"],
                        "evidence": proposal.get("evidence"),
                        "tool_trace": final.get("tool_calls", []),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - surface, never swallow
            logger.exception("recommend stream failed")
            yield _sse({"type": "error", "code": type(exc).__name__, "message": str(exc)[:300]})
        finally:
            T.reset_org_context(org_token)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------
# surplus (FoodLink adapter boundary)
# --------------------------------------------------------------------------
@router.post("/surplus", summary="Create / confirm / withdraw / status a FoodLink listing")
async def surplus(body: SurplusActionRequest, request: Request):
    ctx = _ctx(request, body.org_id)
    try:
        body.validate_for_action()
    except ValueError as exc:
        raise ValidationFailed(str(exc))

    if body.action == "create":
        result = SURPLUS.create_listing(
            ctx.org_id, batch_id=body.batch_id or "", qty=body.qty, confidence=body.confidence
        )
    elif body.action == "confirm":
        result = SURPLUS.confirm_listing(
            ctx.org_id,
            listing_id=body.listing_id or "",
            confirmed_qty=body.confirmed_qty,
            confirmed_by=body.confirmed_by,
            record_impact=body.record_impact,
        )
    elif body.action == "withdraw":
        result = SURPLUS.withdraw_listing(ctx.org_id, listing_id=body.listing_id or "", reason=body.reason)
    else:
        result = SURPLUS.get_listing(ctx.org_id, body.listing_id or "", refresh=True)

    return _envelope({"org_id": ctx.org_id, **result}, request, foodlink=_foodlink_meta())


@router.post("/surplus/create", summary="Publish a forecast listing")
async def surplus_create(body: SurplusCreateRequest, request: Request):
    ctx = _ctx(request, body.org_id)
    result = SURPLUS.create_listing(ctx.org_id, batch_id=body.batch_id, qty=body.qty, confidence=body.confidence)
    return _envelope({"org_id": ctx.org_id, **result}, request, foodlink=_foodlink_meta())


@router.post("/surplus/{listing_id}/confirm", summary="Staff confirms the actual surplus")
async def surplus_confirm(listing_id: str, body: SurplusConfirmRequest, request: Request):
    ctx = _ctx(request, body.org_id)
    result = SURPLUS.confirm_listing(
        ctx.org_id,
        listing_id=listing_id,
        confirmed_qty=body.confirmed_qty,
        confirmed_by=body.confirmed_by,
    )
    return _envelope({"org_id": ctx.org_id, **result}, request, foodlink=_foodlink_meta())


@router.post("/surplus/{listing_id}/withdraw", summary="Surplus did not materialise")
async def surplus_withdraw(listing_id: str, body: SurplusWithdrawRequest, request: Request):
    ctx = _ctx(request, body.org_id)
    result = SURPLUS.withdraw_listing(ctx.org_id, listing_id=listing_id, reason=body.reason)
    return _envelope({"org_id": ctx.org_id, **result}, request, foodlink=_foodlink_meta())


@router.get("/surplus", summary="List this organization's listings")
async def surplus_list(
    request: Request,
    org_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(forecast|confirmed|withdrawn)$"),
    limit: int = Query(50, ge=1, le=500),
):
    ctx = _ctx(request, org_id)
    return _envelope(SURPLUS.list_listings(ctx.org_id, status=status, limit=limit), request, foodlink=_foodlink_meta())


@router.get("/surplus/{listing_id}", summary="Read one listing")
async def surplus_get(
    listing_id: str,
    request: Request,
    org_id: Optional[str] = Query(None),
    refresh: bool = Query(False, description="Also ask FoodLink for its current view"),
):
    ctx = _ctx(request, org_id)
    return _envelope(SURPLUS.get_listing(ctx.org_id, listing_id, refresh=refresh), request, foodlink=_foodlink_meta())


# --------------------------------------------------------------------------
# impact
# --------------------------------------------------------------------------
@router.get("/impact", summary="Aggregated impact by period, location and action")
async def impact(
    request: Request,
    org_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None, max_length=32),
    period: str = Query("all", pattern="^(all|day|week|month)$"),
    since: Optional[str] = Query(None, description="ISO date lower bound, YYYY-MM-DD"),
    until: Optional[str] = Query(None, description="ISO date upper bound, YYYY-MM-DD"),
    limit: int = Query(5000, ge=1, le=20000),
):
    from sqlalchemy import select

    from app.projects.foodlink_predict.db import session_scope
    from app.projects.foodlink_predict.models import ImpactEvent
    from app.projects.foodlink_predict.util import parse_date

    ctx = _ctx(request, org_id)
    try:
        since_d = parse_date(since, field="since") if since else None
        until_d = parse_date(until, field="until") if until else None
    except ValueError as exc:
        raise ValidationFailed(str(exc))

    with session_scope() as sess:
        stmt = select(ImpactEvent).where(ImpactEvent.org_id == ctx.org_id)
        if location_id:
            stmt = stmt.where(ImpactEvent.location_id == location_id)
        if action:
            stmt = stmt.where(ImpactEvent.action_type == action)
        if since_d:
            stmt = stmt.where(ImpactEvent.recorded_at >= since_d)
        if until_d:
            stmt = stmt.where(ImpactEvent.recorded_at < until_d)
        events = list(sess.execute(stmt.limit(limit)).scalars().all())
        aggregate = I.aggregate(events)
        fa = I.false_alarm_stats(sess, ctx.org_id)

    return _envelope(
        {
            "org_id": ctx.org_id,
            "period": period,
            "filters": {
                "location_id": location_id,
                "action": action,
                "since": since,
                "until": until,
                "limit": limit,
            },
            **aggregate,
            "false_alarm_stats": fa,
            "computed_by": "flp.impact (deterministic; never the LLM)",
        },
        request,
    )


# --------------------------------------------------------------------------
# module health
# --------------------------------------------------------------------------
def _foodlink_meta() -> dict:
    from app.projects.foodlink_predict.adapters import describe

    return describe()


@router.get("/health/flp", summary="FoodLink Predict module status")
async def health_flp(request: Request):
    from app.projects.foodlink_predict import db as DB
    from app.projects.foodlink_predict.forecast import sklearn_available

    cfg = get_flp_config()
    safety = get_safety_config()
    return _envelope(
        {
            "enabled": cfg.enabled,
            "demo_mode": cfg.demo_mode,
            "database": {"configured": True, "connected": DB.ping(), "url_scheme": cfg.db_url.split(":")[0], "tables": len(DB.table_names())},
            "ml": {
                "provider": cfg.ml_provider,
                "forecast_model": cfg.forecast_model,
                "sklearn_available": sklearn_available(),
                "note": "Without scikit-learn every series falls back to cold-start and is labelled method='cold_start'",
            },
            "safety": {
                "safe_windows_hours": safety.safe_windows_hours,
                "pickup_lead_time_hours": safety.pickup_lead_time_hours,
                "redistributable_classes": sorted(safety.redistributable_classes),
                "cold_start_days": safety.cold_start_days,
            },
            "impact_factors": {
                "emission_factor_co2e_per_kg": cfg.impact.co2e_kg_per_kg,
                "kg_per_meal": cfg.impact.kg_per_meal,
            },
            "foodlink": _foodlink_meta(),
            "tools": __import__(
                "app.projects.foodlink_predict.tools", fromlist=["all_flp_tools"]
            ).all_flp_tools(),
            "what_is_real": [
                "forecast quantiles (sklearn quantile gradient boosting, or cold-start fallback)",
                "waste risk, urgency, donate-by, action ladder",
                "safety validator",
                "impact arithmetic",
            ],
            "what_is_simulated": [
                "FoodLink hand-off: the demo adapter simulates receipt and stamps demo=true. "
                "No FoodLink agent runs in this process."
            ],
        },
        request,
    )


# The demo scenario is mounted onto the same router so it shares one prefix.
try:  # pragma: no cover - import guard only
    from app.projects.foodlink_predict.demo.routes import router as _demo_router

    router.include_router(_demo_router)
except ImportError:  # pragma: no cover
    logger.warning("demo routes unavailable")

__all__ = ["router"]
