"""Test script for Maps provider."""
from app.maps.provider import distance_km, get_default_provider, set_default_provider, HaversineProvider


def test_maps():
    """Test Maps provider functionality."""
    print("Testing Maps provider...")
    
    # Test haversine distance (two points known to be a few km apart)
    d = distance_km(17.42, 78.48, 17.37, 78.49)
    print(f"  Haversine distance: {d} km")
    assert d > 0, f"Expected positive distance, got {d}"
    print("  - Distance calculation: OK")
    
    # Test default provider
    provider = get_default_provider()
    print(f"  Default provider: {type(provider).__name__}")
    assert isinstance(provider, HaversineProvider), f"Expected HaversineProvider, got {type(provider).__name__}"
    print("  - Default provider: OK")
    
    # Test provider switching
    set_default_provider('haversine')
    provider2 = get_default_provider()
    assert isinstance(provider2, HaversineProvider)
    print("  - Provider switching: OK")
    
    # Test format_address
    formatted = provider.format_address("  12 banjara lane, hyderabad  ")
    print(f"  Formatted address: \"{formatted}\"")
    assert "Banjara" in formatted and "Lane" in formatted
    print("  - Address formatting: OK")
    
    print("\nMaps provider test PASSED!")


if __name__ == "__main__":
    test_maps()