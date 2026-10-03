"""One-call demo scenario endpoint."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.projects.foodlink_predict.demo import scenario
from app.projects.foodlink_predict.tenancy import DEMO_ORG_ID

logger = logging.getLogger("flp.demo")

router = APIRouter()


class ScenarioRequest(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64)
    as_of: Optional[str] = Field(None, description="Pin the clock (ISO-8601) for a reproducible demo")
    seed: int = Field(20261003)
    history_days: int = Field(56, ge=35, le=365)
    confirm: bool = Field(True, description="Confirm the listing and record impact")
    withdraw_one: bool = Field(True, description="Withdraw a second listing to show false-alarm tracking")
    reset: bool = Field(True)
    include_backtest: bool = Field(
        True, description="Run the rolling-origin backtest (slower; switch off for a quick demo)"
    )


@router.post("/demo/scenario", summary="Run the whole FoodLink Predict story offline")
async def run_scenario(body: ScenarioRequest, request: Request):
    from app.projects.foodlink_predict.config import get_flp_config
    from app.projects.foodlink_predict.errors import ValidationFailed
    from app.projects.foodlink_predict.tenancy import resolve_org_id

    cfg = get_flp_config()
    if cfg.adapter_mode == "http" and not cfg.foodlink_api_url:
        raise ValidationFailed(
            "FOODLINK_ADAPTER_MODE=http but FOODLINK_API_URL is empty. "
            "Use FOODLINK_ADAPTER_MODE=demo for the offline demo, or configure the real contract."
        )

    ctx = resolve_org_id(body.org_id)
    result = await scenario.run_async(
        ctx.org_id,
        as_of=body.as_of,
        seed=body.seed,
        history_days=body.history_days,
        confirm=body.confirm,
        withdraw_one=body.withdraw_one,
        reset=body.reset,
        include_backtest=body.include_backtest,
    )
    rid = getattr(request.state, "request_id", "unknown")
    return {"success": True, "data": result, "meta": {"request_id": rid, "module": "foodlink_predict", "demo": True}}


__all__ = ["router"]