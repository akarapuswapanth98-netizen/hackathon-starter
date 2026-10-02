"""Test script for SQLite persistence."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.factory import get_storage_provider
from app.foodbridge.models import FoodSurplus, Restaurant, Shelter
from datetime import datetime, timedelta, timezone


def test_sqlite_persistence():
    """Test that SQLAlchemy provider persists data to SQLite."""
    print("Testing SQLite persistence...")
    
    # Get SQLAlchemy storage provider (default SQLite)
    store = get_storage_provider()
    
    # Add a restaurant
    rest = Restaurant(id='rest-002', name='Test Restaurant', lat=17.42, lon=78.48)
    store.add_restaurant(rest)
    print("  - Added restaurant: rest-002")
    
    # Create a surplus lot
    now = datetime.now(timezone.utc)
    lot = FoodSurplus(
        id='food-002',
        restaurant_id='rest-002',
        meal_count=100,
        food_type='cooked_meals',
        dietary_tags=[],
        prepared_at=now,
        expires_at=now + timedelta(hours=5),
        temperature_c=5.0,
        notes='Test surplus'
    )
    store.add_surplus(lot)
    print(f"  - Added surplus: {lot.id}, meal_count={lot.meal_count}, status={lot.status}")
    
    # Verify it's retrievable
    retrieved = store.get_surplus('food-002')
    assert retrieved is not None, "Surplus not found in store!"
    assert retrieved.id == 'food-002', f"Wrong ID: {retrieved.id}"
    assert retrieved.meal_count == 100, f"Wrong meal_count: {retrieved.meal_count}"
    assert retrieved.status == 'available', f"Wrong status: {retrieved.status}"
    print(f"  - Retrieved surplus: {retrieved.id}, meal_count={retrieved.meal_count}, status={retrieved.status}")
    
    # Test commit_allocation - partial (should keep available status)
    committed = store.commit_allocation('food-002', 50)
    assert committed is not None, "commit_allocation returned None!"
    assert committed.status == 'available', f"Expected 'available' after partial allocation, got {committed.status}"
    assert committed.meal_count == 50, f"Expected meal_count=50, got {committed.meal_count}"
    print(f"  - After partial allocation (50 meals): status={committed.status}, meal_count={committed.meal_count}")
    
    # Test partial allocation again
    committed2 = store.commit_allocation('food-002', 30)  # 30 more, total 80
    assert committed2 is not None, "Second commit_allocation returned None!"
    assert committed2.status == 'available', f"Expected 'available' after partial allocation, got {committed2.status}"
    assert committed2.meal_count == 20, f"Expected meal_count=20, got {committed2.meal_count}"
    print(f"  - After second partial allocation (30 more): status={committed2.status}, meal_count={committed2.meal_count}")
    
    # Test full allocation (should set to allocated)
    committed3 = store.commit_allocation('food-002', 20)  # would make total 100, equal to original meal_count
    assert committed3 is not None, "Third commit_allocation returned None!"
    assert committed3.status == 'allocated', f"Expected 'allocated' after full allocation, got {committed3.status}"
    assert committed3.meal_count == 20, f"Expected meal_count=20 (preserved), got {committed3.meal_count}"
    print(f"  - After full allocation (20 more): status={committed3.status}, meal_count={committed3.meal_count}")
    
    # Test that consumed/allocated lots return proper 409
    committed4 = store.commit_allocation('food-002', 10)  # lot is now allocated
    # When status != available, commit_allocation returns the model, not a 409 JSON response
    # (the 409 is handled at the API layer)
    assert committed4 is not None, "commit_allocation on allocated lot should return model"
    print(f"  - Allocated lot re-attempt: status={committed4.status}, meal_count={committed4.meal_count}")
    
    # Test list_available_surpluses
    available = store.list_available_surpluses()
    print(f"  - Available surpluses: {len(available)}")
    
    # Test reset
    store.reset()
    print(f"  - After reset: surpluses={store.list_available_surpluses()}, restaurants={store.list_restaurants()}")
    
    print("\nSQLite persistence test PASSED!")


if __name__ == "__main__":
    test_sqlite_persistence()