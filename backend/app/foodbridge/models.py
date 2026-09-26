"""Pydantic models for FoodBridge - API payloads and domain records."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

Urgency = Literal["high", "medium", "low"]
SurplusStatus = Literal["available", "allocated"]
MatchStatus = Literal["completed", "failed", "timeout"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Restaurant(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    address: str = ""
    cuisine_types: List[str] = Field(default_factory=list)
    contact: str = ""


class FoodSurplus(BaseModel):
    id: str
    restaurant_id: str
    meal_count: int = Field(gt=0)
    food_type: str = "cooked_meals"
    dietary_tags: List[str] = Field(default_factory=list, description='e.g. ["vegetarian"]')
    prepared_at: datetime
    expires_at: datetime
    temperature_c: float = 5.0
    notes: str = ""
    status: SurplusStatus = "available"

    def hours_remaining(self, now: Optional[datetime] = None) -> float:
        now = now or utcnow()
        return (self.expires_at - now).total_seconds() / 3600.0


class Shelter(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    capacity: int = Field(gt=0)
    current_occupancy: int = Field(default=0, ge=0)
    urgency: Urgency = "medium"
    food_requirements: List[str] = Field(default_factory=list, description='e.g. ["vegetarian"]')
    address: str = ""


class CreateSurplusRequest(BaseModel):
    restaurant_id: str
    meal_count: int = Field(gt=0, description="Number of surplus meals")
    food_type: str = "cooked_meals"
    dietary_tags: List[str] = Field(default_factory=list, description='e.g. ["vegetarian"]')
    expires_in_hours: float = Field(default=5.0, gt=0, le=168)
    temperature_c: float = 5.0
    notes: str = ""


class MatchOptions(BaseModel):
    max_shelters: Optional[int] = Field(default=None, ge=1, description="Cap on shelters receiving meals")
    include_summary: bool = Field(default=True, description="Generate natural-language summary")


class MatchRequest(BaseModel):
    surplus_id: Optional[str] = None
    requested_radius_km: float = Field(default=10.0, gt=0, le=100, description="Only match shelters within this radius")
    shelter_ids: Optional[List[str]] = None
    options: MatchOptions = Field(default_factory=MatchOptions)


class Allocation(BaseModel):
    shelter_id: str
    shelter_name: str
    meals: int
    distance_km: float
    score: float
    breakdown: Dict[str, Dict[str, float]] = Field(default_factory=dict)


class AgentEvent(BaseModel):
    workflow_id: str
    agent: str
    status: Literal["running", "completed", "failed"]
    detail: str
    timestamp: datetime


class MatchResponse(BaseModel):
    """POST /api/foodbridge/match response - spec keys first, additive extras after."""
    success: bool
    workflow_id: str
    workflow_status: MatchStatus
    allocation: List[Allocation] = Field(default_factory=list)
    agent_events: List[AgentEvent] = Field(default_factory=list)
    total_allocated: int = 0
    unallocated: int = 0
    summary: str = ""
    summary_source: str = "skipped"
    retry_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
