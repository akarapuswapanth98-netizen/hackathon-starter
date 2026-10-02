"""Abstract base class for storage providers.

Note: Concrete implementations (SQLAlchemy, in-memory) import models as needed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Restaurant(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    address: str = ""
    cuisine_types: List[str] = []
    contact: str = ""


class FoodSurplus(BaseModel):
    id: str
    restaurant_id: str
    meal_count: int = Field(gt=0)
    food_type: str = "cooked_meals"
    dietary_tags: List[str] = Field(default_factory=list)
    prepared_at: datetime
    expires_at: datetime
    temperature_c: float = 5.0
    notes: str = ""
    status: str = "available"

    def hours_remaining(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (self.expires_at - now).total_seconds() / 3600.0


class Shelter(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    capacity: int = Field(gt=0)
    current_occupancy: int = Field(default=0, ge=0)
    urgency: str = "medium"
    food_requirements: List[str] = Field(default_factory=list)
    address: str = ""


class StorageProvider(ABC):
    """Abstract storage provider - implement for SQLAlchemy, in-memory, etc."""

    # --- Restaurants ---
    @abstractmethod
    def get_restaurant(self, restaurant_id: str) -> Optional[Restaurant]:
        pass

    @abstractmethod
    def list_restaurants(self) -> List[Restaurant]:
        pass

    @abstractmethod
    def add_restaurant(self, restaurant: Restaurant) -> Restaurant:
        pass

    # --- Surplus ---
    @abstractmethod
    def get_surplus(self, surplus_id: str) -> Optional[FoodSurplus]:
        pass

    @abstractmethod
    def list_surpluses(self, restaurant_id: Optional[str] = None) -> List[FoodSurplus]:
        pass

    @abstractmethod
    def list_available_surpluses(self, restaurant_id: Optional[str] = None) -> List[FoodSurplus]:
        pass

    @abstractmethod
    def latest_surplus(self, restaurant_id: Optional[str] = None) -> Optional[FoodSurplus]:
        pass

    @abstractmethod
    def add_surplus(self, lot: FoodSurplus) -> FoodSurplus:
        pass

    @abstractmethod
    def commit_allocation(self, surplus_id: str, total_allocated: int) -> Optional[FoodSurplus]:
        pass

    @abstractmethod
    def reserve_surplus(self, surplus_id: str) -> bool:
        pass

    @abstractmethod
    def release_surplus(self, surplus_id: str) -> None:
        pass

    # --- Shelters ---
    @abstractmethod
    def get_shelter(self, shelter_id: str) -> Optional[Shelter]:
        pass

    @abstractmethod
    def list_shelters(self) -> List[Shelter]:
        pass

    @abstractmethod
    def add_shelter(self, shelter: Shelter) -> Shelter:
        pass

    # --- Lifecycle ---
    @abstractmethod
    def reset(self) -> None:
        """Restore pristine demo data."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Clean up resources (connections, etc.)."""
        pass

    # --- Match History / Audit ---
    @abstractmethod
    def record_match_result(
        self,
        workflow_id: str,
        surplus_id: str,
        allocations: List[Dict[str, Any]],
        total_allocated: int,
        unallocated: int,
        status: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Record a completed match for audit/history."""
        pass

    @abstractmethod
    def get_match_history(
        self,
        surplus_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get match history for audit."""
        pass