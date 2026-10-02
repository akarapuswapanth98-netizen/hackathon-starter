"""Maps provider abstraction - optional external provider integration with haversine fallback."""

from .provider import (
    MapsProvider,
    HaversineProvider,
    get_provider,
    set_default_provider,
    get_default_provider,
    distance_km,
)

__all__ = [
    "MapsProvider",
    "HaversineProvider",
    "get_provider",
    "set_default_provider",
    "get_default_provider",
    "distance_km",
]