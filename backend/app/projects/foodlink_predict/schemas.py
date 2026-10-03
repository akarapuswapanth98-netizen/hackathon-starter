"""Pydantic request/response models.

Request models validate at the edge so a malformed request never reaches the
pipeline. Response models are intentionally permissive (``dict``/``list``) for
the computed payloads: the *shape* of a forecast band or a validator issue is
already enforced by Pydantic models deeper in the stack, and duplicating it here
would mean maintaining the same contract twice.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class IngestRequest(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64, description="Organization scope; defaults to the demo org")
    csv_text: str = Field(..., min_length=1, max_length=2_000_000, description="Raw CSV content")
    kind: Optional[Literal["sales", "inventory", "items", "calendar"]] = Field(None, description="CSV type; auto-detected when omitted")
    source: Literal["uploaded", "synthetic"] = Field("uploaded", description="Provenance label persisted on every row")

    @field_validator("csv_text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("csv_text must not be blank")
        return v


class IngestBatchRequest(BaseModel):
    files: list[IngestRequest] = Field(..., min_length=1, max_length=20, description="Multiple CSV payloads in one call")


class DemoSeedRequest(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64, description="Organization scope; defaults to the demo org")
    history_days: int = Field(56, ge=35, le=365, description="Synthetic sales history length")
    seed: int = Field(20261003, description="RNG seed; identical seeds give identical data")
    reset: bool = Field(False, description="Delete this org's existing FLP rows first")


class ForecastRequest(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64)
    location_id: Optional[str] = Field(None, max_length=64, description="Restrict to one location")
    horizon_days: int = Field(7, ge=1, le=60)
    include_backtest: bool = Field(True, description="Run the rolling-origin evaluation")


class RiskQuery(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64)
    location_id: Optional[str] = Field(None, max_length=64)
    min_risk: float = Field(0.0, ge=0.0, le=1.0)
    batch_id: Optional[str] = Field(None, max_length=64)
    limit: int = Field(50, ge=1, le=500)
    recompute: bool = Field(True, description="Recompute risk from current inventory + forecast")


class RecommendRequest(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64)
    location_id: Optional[str] = Field(None, max_length=64)
    batch_id: Optional[str] = Field(None, max_length=64)
    min_risk: float = Field(0.0, ge=0.0, le=1.0)
    limit: int = Field(5, ge=1, le=50)
    persist: bool = Field(True)


class SurplusCreateRequest(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64)
    batch_id: str = Field(..., min_length=1, max_length=64)
    qty: Optional[float] = Field(None, gt=0, description="Quantity to list; defaults to the validated recommendation quantity")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class SurplusConfirmRequest(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64)
    confirmed_qty: Optional[float] = Field(None, gt=0, description="Actual quantity staff verified")
    confirmed_by: Optional[str] = Field(None, max_length=128)


class SurplusWithdrawRequest(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64)
    reason: str = Field("surplus_did_not_materialise", max_length=255)


class SurplusActionRequest(BaseModel):
    """Body for POST /api/surplus with an explicit action, per the PDF's contract."""

    action: Literal["create", "confirm", "withdraw", "status"] = Field(..., description="Listing operation")
    org_id: Optional[str] = Field(None, max_length=64)
    batch_id: Optional[str] = Field(None, max_length=64, description="Required for action=create")
    listing_id: Optional[str] = Field(None, max_length=64, description="Required for confirm/withdraw/status")
    qty: Optional[float] = Field(None, gt=0)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    confirmed_qty: Optional[float] = Field(None, gt=0)
    confirmed_by: Optional[str] = Field(None, max_length=128)
    reason: str = Field("surplus_did_not_materialise", max_length=255)
    record_impact: bool = Field(True)

    def validate_for_action(self) -> None:
        if self.action == "create" and not self.batch_id:
            raise ValueError("batch_id is required when action='create'")
        if self.action in ("confirm", "withdraw", "status") and not self.listing_id:
            raise ValueError(f"listing_id is required when action='{self.action}'")


class ImpactQuery(BaseModel):
    org_id: Optional[str] = Field(None, max_length=64)
    location_id: Optional[str] = Field(None, max_length=64)
    action: Optional[str] = Field(None, max_length=32)
    period: Literal["all", "day", "week", "month"] = Field("all")
    since: Optional[str] = Field(None, max_length=10, description="ISO date lower bound, YYYY-MM-DD")
    until: Optional[str] = Field(None, max_length=10, description="ISO date upper bound, YYYY-MM-DD")
    limit: int = Field(500, ge=1, le=5000)


class RiskItem(BaseModel):
    batch_id: str
    item_id: str
    item_name: str
    location_id: Optional[str] = None
    stock_qty: float
    expected_unsold: float
    risk: float
    urgency_hours: float
    donate_by: Optional[str] = None
    priority: float
    value_at_risk: float
    status: str
    safe_to_donate: bool
    redistributable: bool
    horizon_days: int
    insufficient_history: bool
    model_version: str


class RiskResponse(BaseModel):
    org_id: str
    count: int
    items: list[RiskItem]
    safety_config: dict[str, Any]
    computed_at: str


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    path: Optional[str] = None