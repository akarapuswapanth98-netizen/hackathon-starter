"""FoodLink integration boundary.

Isolated deliberately: importing anything from ``app.projects.foodlink_predict``
outside of ``adapters/`` cannot reach FoodLink's schema. The only supported
entry points are ``factory.get_adapter`` and ``base.canonical_listing``.
"""

from app.projects.foodlink_predict.adapters.base import (
    FoodLinkAdapter,
    FoodLinkError,
    FoodLinkUnavailable,
    ListingRejected,
    canonical_listing,
)
from app.projects.foodlink_predict.adapters.factory import describe, get_adapter, reset_adapters

__all__ = [
    "FoodLinkAdapter",
    "FoodLinkError",
    "FoodLinkUnavailable",
    "ListingRejected",
    "canonical_listing",
    "describe",
    "get_adapter",
    "reset_adapters",
]