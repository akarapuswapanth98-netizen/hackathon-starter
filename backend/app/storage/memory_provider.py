"""In-memory storage provider - wraps existing FoodBridge store for tests."""
from typing import Any, Dict, List, Optional

from app.foodbridge.models import FoodSurplus, Restaurant, Shelter
from app.foodbridge.store import get_store, reset_store
from app.storage.base import StorageProvider


class MemoryProvider(StorageProvider):
    """In-memory storage using existing FoodBridge store - for tests."""

    def __init__(self):
        # Ensure store is initialized
        get_store()

    def get_restaurant(self, restaurant_id: str) -> Optional[Restaurant]:
        return get_store().get_restaurant(restaurant_id)

    def list_restaurants(self) -> List[Restaurant]:
        return get_store().list_restaurants()

    def add_restaurant(self, restaurant: Restaurant) -> Restaurant:
        return get_store().add_restaurant(restaurant)

    def get_surplus(self, surplus_id: str) -> Optional[FoodSurplus]:
        return get_store().get_surplus(surplus_id)

    def list_surpluses(self, restaurant_id: Optional[str] = None) -> List[FoodSurplus]:
        return get_store().list_surpluses(restaurant_id)

    def list_available_surpluses(self, restaurant_id: Optional[str] = None) -> List[FoodSurplus]:
        return get_store().list_available_surpluses(restaurant_id)

    def latest_surplus(self, restaurant_id: Optional[str] = None) -> Optional[FoodSurplus]:
        return get_store().latest_surplus(restaurant_id)

    def add_surplus(self, lot: FoodSurplus) -> FoodSurplus:
        return get_store().add_surplus(lot)

    def commit_allocation(self, surplus_id: str, total_allocated: int) -> Optional[FoodSurplus]:
        return get_store().commit_allocation(surplus_id, total_allocated)

    def reserve_surplus(self, surplus_id: str) -> bool:
        return get_store().reserve_surplus(surplus_id)

    def release_surplus(self, surplus_id: str) -> None:
        get_store().release_surplus(surplus_id)

    def get_shelter(self, shelter_id: str) -> Optional[Shelter]:
        return get_store().get_shelter(shelter_id)

    def list_shelters(self) -> List[Shelter]:
        return get_store().list_shelters()

    def add_shelter(self, shelter: Shelter) -> Shelter:
        return get_store().add_shelter(shelter)

    def reset(self) -> None:
        reset_store()

    def close(self) -> None:
        pass  # No resources to clean up

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
        # In-memory doesn't persist history
        pass

    def get_match_history(
        self,
        surplus_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return []