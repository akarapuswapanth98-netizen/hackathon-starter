"""MapsProvider abstraction with haversine fallback and optional external provider stubs.

This module defines a common interface for maps/distance operations, with a built-in
haversine fallback that requires no external dependencies. Other providers (OSRM, Google
Maps, Mapbox) are stubbed for future integration without breaking the core API.
"""

import math
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Union


class MapsProvider(ABC):
    """Abstract base class for maps/distance providers."""

    @abstractmethod
    def haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate the great-circle distance in kilometers between two points.

        Args:
            lat1: Latitude of point 1 (degrees)
            lon1: Longitude of point 1 (degrees)
            lat2: Latitude of point 2 (degrees)
            lon2: Longitude of point 2 (degrees)

        Returns:
            Distance in kilometers
        """
        pass

    @abstractmethod
    def format_address(self, raw_address: str) -> str:
        """Normalize/format an address string.

        Args:
            raw_address: Raw address string

        Returns:
            Formatted address string
        """
        pass


class HaversineProvider(MapsProvider):
    """Concrete implementation using the haversine formula - no external dependencies.

    This is the default provider and works entirely offline. It's used by FoodBridge
    for surplus-to-shelter distance calculations.
    """

    _earth_radius_km = 6371.0  # Earth's mean radius in kilometers

    def haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate the great-circle distance in kilometers between two points.

        Uses the haversine formula: a = sin²(Δφ/2) + cos(φ1) · cos(φ2) · sin²(Δλ/2)
        c = 2 · atan2(√a, √(1−a))
        d = R · c

        Args:
            lat1: Latitude of point 1 (degrees)
            lon1: Longitude of point 1 (degrees)
            lat2: Latitude of point 2 (degrees)
            lon2: Longitude of point 2 (degrees)

        Returns:
            Distance in kilometers
        """
        # Convert decimal degrees to radians
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        # Haversine formula
        a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        distance = self._earth_radius_km * c
        return round(distance, 4)

    def format_address(self, raw_address: str) -> str:
        """Normalize an address string (basic cleanup only).

        Args:
            raw_address: Raw address string

        Returns:
            Cleaned address string (title case, trimmed)
        """
        if not raw_address:
            return ""
        # Basic cleanup: strip whitespace, fix common issues
        cleaned = raw_address.strip()
        # Simple title case (not perfect but works for most addresses)
        cleaned = " ".join(word.capitalize() for word in cleaned.split())
        return cleaned


# Provider registry - map provider name to instance
_provider_instances: dict[str, MapsProvider] = {}
_default_provider: MapsProvider = HaversineProvider()


def get_provider(name: str = "haversine") -> MapsProvider:
    """Get a maps provider instance by name.

    Args:
        name: Provider name ("haversine", "osrm", "google", "mapbox")

    Returns:
        MapsProvider instance
    """
    if name not in _provider_instances:
        if name == "haversine":
            _provider_instances[name] = HaversineProvider()
        elif name == "osrm":
            from .provider_stub import OSRMProvider
            _provider_instances[name] = OSRMProvider()
        elif name == "google":
            from .provider_stub import GoogleMapsProvider
            _provider_instances[name] = GoogleMapsProvider()
        elif name == "mapbox":
            from .provider_stub import MapboxProvider
            _provider_instances[name] = MapboxProvider()
        else:
            _provider_instances[name] = HaversineProvider()

    return _provider_instances[name]


def set_default_provider(name: str) -> None:
    """Set the default provider for the application.

    Args:
        name: Provider name ("haversine", "osrm", "google", "mapbox")
    """
    global _default_provider
    _default_provider = get_provider(name)


def get_default_provider() -> MapsProvider:
    """Get the default maps provider.

    Returns:
        MapsProvider instance
    """
    return _default_provider


# Convenience function - calculate distance using the default provider
def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points using the default provider.

    Args:
        lat1: Latitude of point 1
        lon1: Longitude of point 1
        lat2: Latitude of point 2
        lon2: Longitude of point 2

    Returns:
        Distance in kilometers
    """
    return get_default_provider().haversine_km(lat1, lon1, lat2, lon2)


# Stub provider modules (imported lazily)

class _BaseStubProvider(MapsProvider):
    """Base class for stub providers that can be replaced with real implementations."""

    def format_address(self, raw_address: str) -> str:
        return raw_address.strip().title() if raw_address else ""


class OSRMProvider(_BaseStubProvider):
    """Stub OSRM (Open Source Routing Machine) provider.

    Replace with real implementation by setting OSRM_BASE_URL environment variable.
    """

    def __init__(self):
        self.base_url = "http://router.project-osrm.org/route/v1/driving"
        # In a real deployment, this would read from:
        # os.getenv("OSRM_BASE_URL", "http://router.project-osrm.org/route/v1/driving")


class GoogleMapsProvider(_BaseStubProvider):
    """Stub Google Maps provider.

    Replace with real implementation by setting GOOGLE_MAPS_API_KEY.
    """

    def __init__(self):
        self.api_key = ""  # os.getenv("GOOGLE_MAPS_API_KEY", "")


class MapboxProvider(_BaseStubProvider):
    """Stub Mapbox provider.

    Replace with real implementation by setting MAPBOX_ACCESS_TOKEN.
    """

    def __init__(self):
        self.access_token = ""  # os.getenv("MAPBOX_ACCESS_TOKEN", "")