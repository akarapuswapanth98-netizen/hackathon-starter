"""FoodLink Predict agent tools.

Registered into the toolkit's own ``app.agents.tools.TOOL_REGISTRY`` via
``@register_tool``, so they appear in ``tool_specs()`` and the LLM can see them
exactly like any starter tool. That is the extension point the toolkit
documents ("add a new tool in under 10 lines"); no second tool framework is
introduced.

Structured data, not prose
--------------------------
The toolkit's ``call_tool`` returns a string because a text LLM needs text. To
keep that contract *and* guarantee the agent never has to parse prose, every
tool returns ``json.dumps(payload)`` AND exposes a typed ``invoke()`` returning
the same payload as a dict. The agent uses ``invoke``; the LLM path gets JSON
it can read reliably. The LLM therefore never computes a number - it only reads
the deterministic ones this module computed.

Tenancy
-------
Tools run inside an agent turn, which has no request object. The org scope is
carried in a ContextVar set by the service layer, so a tool physically cannot be
called without a tenant and cannot read another tenant's rows.
"""

from __future__ import annotations

import contextvars
import datetime as _dt
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.tools import register_tool

logger = logging.getLogger("flp.tools")

_ORG_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar("flp_org_id", default=None)
_BATCH_CTX: contextvars.ContextVar[dict | None] = contextvars.ContextVar("flp_batch_ctx", default=None)


def set_org_context(org_id: str | None) -> contextvars.Token:
    return _ORG_CTX.set(org_id)


def reset_org_context(token: contextvars.Token) -> None:
    _ORG_CTX.reset(token)


def set_batch_context(ctx: dict | None) -> contextvars.Token:
    return _BATCH_CTX.set(ctx)


def reset_batch_context(token: contextvars.Token) -> None:
    _BATCH_CTX.reset(token)


def current_org_id() -> str:
    org_id = _ORG_CTX.get()
    if not org_id:
        raise PermissionError("No organization scope bound to this agent turn")
    return org_id


def _json(payload: Any) -> str:
    return json.dumps(payload, default=str)


# --------------------------------------------------------------------------
# 1. get_forecast
# --------------------------------------------------------------------------
class GetForecastArgs(BaseModel):
    item_id: str = Field(..., description="Item id, e.g. itm_cooked_rice")
    location_id: str = Field(..., description="Location id, e.g. loc_main_canteen")
    horizon_days: int = Field(7, ge=1, le=60, description="Days to forecast forward")


@register_tool(
    "get_forecast",
    "Read stored P10/P50/P90 demand forecast for one item at one location. Returns numbers only; never compute them.",
    GetForecastArgs,
)
async def get_forecast(item_id: str, location_id: str, horizon_days: int = 7) -> str:
    return _json(invoke_get_forecast(item_id, location_id, horizon_days))


def invoke_get_forecast(item_id: str, location_id: str, horizon_days: int = 7) -> dict:
    from app.projects.foodlink_predict.db import session_scope
    from app.projects.foodlink_predict.models import Forecast
    from sqlalchemy import select

    org_id = current_org_id()
    with session_scope() as sess:
        rows = list(
            sess.execute(
                select(Forecast)
                .where(
                    Forecast.org_id == org_id,
                    Forecast.item_id == item_id,
                    Forecast.location_id == location_id,
                )
                .order_by(Forecast.target_date)
            )
            .scalars()
            .all()
        )
    # Keep the newest model version when several exist for the same date.
    newest: dict[_dt.date, Forecast] = {}
    for r in rows:
        newest.setdefault(r.target_date, r)
    points = [
        {
            "target_date": d.isoformat(),
            "p10": round(float(r.p10), 3),
            "p50": round(float(r.p50), 3),
            "p90": round(float(r.p90), 3),
            "model_version": r.model_version,
            "method": r.method,
        }
        for d, r in sorted(newest.items())
    ][: max(1, int(horizon_days))]
    return {
        "item_id": item_id,
        "location_id": location_id,
        "horizon_days": horizon_days,
        "points": points,
        "point_count": len(points),
        "found": bool(points),
        "basis": "stored model output; regenerate with POST /api/forecast",
    }


# --------------------------------------------------------------------------
# 2. get_risk_items
# --------------------------------------------------------------------------
class GetRiskItemsArgs(BaseModel):
    location_id: str = Field("", description="Location id; empty means all locations")
    min_risk: float = Field(0.0, ge=0.0, le=1.0, description="Minimum risk score to include")
    limit: int = Field(20, ge=1, le=200)


@register_tool(
    "get_risk_items",
    "List inventory batches ranked by waste-risk priority, with risk, urgency and donate-by.",
    GetRiskItemsArgs,
)
async def get_risk_items(location_id: str = "", min_risk: float = 0.0, limit: int = 20) -> str:
    return _json(invoke_get_risk_items(location_id, min_risk, limit))


def invoke_get_risk_items(location_id: str = "", min_risk: float = 0.0, limit: int = 20) -> dict:
    from app.projects.foodlink_predict.db import list_where, session_scope
    from app.projects.foodlink_predict.models import WasteRisk

    org_id = current_org_id()
    with session_scope() as sess:
        rows = list_where(
            sess,
            WasteRisk,
            org_id,
            location_id=location_id or None,
            limit=1000,
        )
    out = []
    for r in rows:
        detail = r.detail or {}
        if float(r.risk) < float(min_risk):
            continue
        out.append(
            {
                "batch_id": r.batch_id,
                "location_id": detail.get("location_id"),
                "expected_unsold": round(float(r.expected_unsold), 2),
                "risk": round(float(r.risk), 4),
                "urgency_hours": round(float(r.urgency_hours), 1),
                "donate_by": r.donate_by.isoformat() if r.donate_by else None,
                "priority": round(float(r.priority), 3),
                "status": detail.get("status"),
            }
        )
    out.sort(key=lambda x: -x["priority"])
    return {
        "location_id": location_id or "all",
        "min_risk": float(min_risk),
        "count": len(out),
        "items": out[: int(limit)],
    }


# --------------------------------------------------------------------------
# 3. rank_actions
# --------------------------------------------------------------------------
class RankActionsArgs(BaseModel):
    batch_id: str = Field(..., description="Batch id to rank actions for")


@register_tool(
    "rank_actions",
    "Apply the deterministic recovery ladder to a batch. Returns every action with allow/deny and the reason.",
    RankActionsArgs,
)
async def rank_actions(batch_id: str) -> str:
    return _json(invoke_rank_actions(batch_id))


def invoke_rank_actions(batch_id: str) -> dict:
    ctx = _BATCH_CTX.get()
    if not ctx:
        return {"error": "rank_actions called outside a recommendation turn", "batch_id": batch_id}
    return {
        "batch_id": batch_id,
        "ladder": ctx.get("ladder", []),
        "risk": ctx.get("risk"),
        "preferred_action": ctx.get("preferred_action"),
        "allowed_actions": ctx.get("allowed_actions", []),
        "note": "Only these actions are permitted. The validator re-checks whichever you select.",
    }


# --------------------------------------------------------------------------
# 4. create_promo
# --------------------------------------------------------------------------
class CreatePromoArgs(BaseModel):
    batch_id: str = Field(...)
    discount: float = Field(0.3, ge=0.0, le=1.0, description="Discount fraction 0-1")


@register_tool(
    "create_promo",
    "Draft a markdown promotion for a batch and return its deterministic economics.",
    CreatePromoArgs,
)
async def create_promo(batch_id: str, discount: float = 0.3) -> str:
    return _json(invoke_create_promo(batch_id, discount))


def invoke_create_promo(batch_id: str, discount: float = 0.3) -> dict:
    from app.projects.foodlink_predict.actions import promotion_math
    from app.projects.foodlink_predict.config import ACTION_PROMOTION, ActionRule

    ctx = _BATCH_CTX.get()
    if not ctx:
        return {"error": "create_promo called outside a recommendation turn", "batch_id": batch_id}
    ladder = {c["action"]: c for c in ctx.get("ladder", [])}
    promo = ladder.get(ACTION_PROMOTION)
    if not promo or not promo.get("allowed"):
        return {
            "batch_id": batch_id,
            "created": False,
            "reason": (promo or {}).get("reason", "promotion is not on the allowed ladder for this batch"),
        }
    item = ctx.get("item") or {}
    qty = float(promo.get("quantity") or 0.0)
    math = promotion_math(
        qty=qty,
        unit_price=float(item.get("unit_price", 0.0) or 0.0),
        unit_cost=float(item.get("unit_cost", 0.0) or 0.0),
        discount_fraction=discount,
        rules=ActionRule(),
    )
    return {
        "batch_id": batch_id,
        "created": True,
        "requested_discount": discount,
        "economics": math,
        "expected_clearance_qty": qty,
        "deadline": promo.get("deadline"),
        "note": "Economics are computed by code. Do not restate or adjust them.",
    }


# --------------------------------------------------------------------------
# 5. propose_transfer
# --------------------------------------------------------------------------
class ProposeTransferArgs(BaseModel):
    batch_id: str = Field(...)
    destination_id: str = Field("", description="Destination location id; empty evaluates all")


@register_tool(
    "propose_transfer",
    "Check transfer feasibility to another location: forecast headroom, distance and whether it fits before donate-by.",
    ProposeTransferArgs,
)
async def propose_transfer(batch_id: str, destination_id: str = "") -> str:
    return _json(invoke_propose_transfer(batch_id, destination_id))


def invoke_propose_transfer(batch_id: str, destination_id: str = "") -> dict:
    ctx = _BATCH_CTX.get()
    if not ctx:
        return {"error": "propose_transfer called outside a recommendation turn", "batch_id": batch_id}
    options = (ctx.get("ladder") or [{}])
    for c in options:
        if c.get("action") == "transfer":
            plans = (c.get("detail") or {}).get("options", [])
            if destination_id:
                plans = [p for p in plans if p.get("destination_id") == destination_id]
            return {
                "batch_id": batch_id,
                "allowed": bool(c.get("allowed")),
                "reason": c.get("reason"),
                "options": plans,
                "note": "ETA is estimated from haversine distance, not live routing.",
            }
    return {"batch_id": batch_id, "allowed": False, "options": [], "reason": "transfer was not evaluated"}


# --------------------------------------------------------------------------
# 6. create_surplus_listing
# --------------------------------------------------------------------------
class CreateSurplusListingArgs(BaseModel):
    batch_id: str = Field(...)
    qty: float = Field(0.0, ge=0.0, description="Quantity to list; 0 means all stock on hand")


@register_tool(
    "create_surplus_listing",
    "Build a FoodLink-compatible forecast listing for a batch. Safety-gated: refused if past donate-by or unsafe.",
    CreateSurplusListingArgs,
)
async def create_surplus_listing(batch_id: str, qty: float = 0.0) -> str:
    return _json(invoke_create_surplus_listing(batch_id, qty))


def invoke_create_surplus_listing(batch_id: str, qty: float = 0.0) -> dict:
    ctx = _BATCH_CTX.get()
    if not ctx:
        return {"error": "create_surplus_listing called outside a recommendation turn", "batch_id": batch_id}
    ladder = {c["action"]: c for c in ctx.get("ladder", [])}
    donate = ladder.get("donate") or {}
    if not donate.get("allowed"):
        return {
            "batch_id": batch_id,
            "created": False,
            "reason": donate.get("reason", "donation is not permitted for this batch"),
            "reminder": "The validator will refuse this regardless; choose another action.",
        }
    planned = float(qty or donate.get("quantity") or 0.0)
    return {
        "batch_id": batch_id,
        "created": False,
        "dry_run": True,
        "planned_qty": planned,
        "donate_by": donate.get("deadline"),
        "confidence_hint": (donate.get("detail") or {}).get("confidence_hint"),
        "note": "Listing creation is performed by POST /api/surplus after the validator passes, not by the LLM.",
    }


def all_flp_tools() -> dict[str, str]:
    """Names of the tools this project contributes to the shared registry."""
    return {
        "get_forecast": "Read P10/P50/P90 forecast",
        "get_risk_items": "Ranked at-risk batches",
        "rank_actions": "Deterministic recovery ladder",
        "create_promo": "Markdown promotion economics",
        "propose_transfer": "Transfer feasibility + ETA",
        "create_surplus_listing": "Forecast listing (dry run)",
    }


__all__ = [
    "all_flp_tools",
    "current_org_id",
    "create_promo",
    "create_surplus_listing",
    "get_forecast",
    "get_risk_items",
    "invoke_create_promo",
    "invoke_create_surplus_listing",
    "invoke_get_forecast",
    "invoke_get_risk_items",
    "invoke_propose_transfer",
    "invoke_rank_actions",
    "propose_transfer",
    "rank_actions",
    "reset_batch_context",
    "reset_org_context",
    "set_batch_context",
    "set_org_context",
]