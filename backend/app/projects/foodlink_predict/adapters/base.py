"""The ONE seam between FoodLink Predict and FoodLink.

The brief and the PDF agree on this point: the real FoodLink listing schema is
**unverified**. The architecture PDF says so explicitly ("I could not inspect
it"), so this package does not guess one. Instead it defines:

* ``canonical_listing()`` - Predict's own, stable, versioned listing shape.
* ``FoodLinkAdapter`` - the interface (4 methods) with one file's worth of
  translation logic.
* ``DemoFoodLinkAdapter`` - a fully offline implementation that stores listings
  and simulates receipt by FoodLink's Detect agent. Every response it returns is
  stamped ``demo=True`` / ``simulated=True`` so no UI can present it as a real
  hand-off.
* ``HttpFoodLinkAdapter`` - present but *disabled unless* an endpoint path is
  configured. It refuses loudly rather than POSTing a guessed payload to
  someone's production system.

To wire the real FoodLink, edit ``map_to_foodlink_payload`` (and, if needed,
``parse_response``) in ``http.py``. Nothing else in the codebase changes: no
route, no agent, no model.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Protocol, runtime_checkable

from app.projects.foodlink_predict.config import LISTING_SOURCE, LISTING_STATUSES
from app.projects.foodlink_predict.util import as_utc, iso, utcnow


class FoodLinkError(RuntimeError):
    """Adapter-level failure. Carries a reason code for the API layer."""

    def __init__(self, message: str, reason: str = "adapter_error", status_code: int = 502) -> None:
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code


class FoodLinkUnavailable(FoodLinkError):
    def __init__(self, message: str, reason: str = "unavailable", status_code: int = 503) -> None:
        super().__init__(message, reason, status_code)


class ListingRejected(FoodLinkError):
    def __init__(self, message: str, reason: str = "rejected", status_code: int = 422) -> None:
        super().__init__(message, reason, status_code)


def canonical_listing(
    *,
    listing_id: str,
    org_id: str,
    location: dict,
    items: list[dict],
    ready_at: _dt.datetime | None,
    donate_by: _dt.datetime | None,
    storage: str,
    confidence: float,
    status: str = "forecast",
) -> dict:
    """Predict's canonical listing document (PDF section 5).

    This shape is Predict's own contract. It is stable and versioned so the
    translation to the real FoodLink schema can change independently.
    """
    if status not in LISTING_STATUSES:
        raise FoodLinkError(f"invalid listing status '{status}'", reason="invalid_status", status_code=422)
    return {
        "contract_version": "flp-listing/1",
        "listing_id": listing_id,
        "org_id": org_id,
        "location": {
            "id": location.get("id"),
            "name": location.get("name"),
            "lat": location.get("lat"),
            "lng": location.get("lng"),
            "timezone": location.get("timezone", "UTC"),
        },
        "items": [
            {
                "item_id": it.get("item_id"),
                "name": it.get("name"),
                "category": it.get("category"),
                "food_class": it.get("food_class"),
                "qty": it.get("qty"),
                "qty_kg": it.get("qty_kg"),
                "unit": it.get("unit"),
                # `cooked` is the flag FoodLink's contract in the PDF calls out.
                "cooked": str(it.get("food_class", "")).lower() == "cooked",
            }
            for it in items
        ],
        "ready_at": iso(as_utc(ready_at)),
        "donate_by": iso(as_utc(donate_by)),
        "storage": storage,
        "confidence": round(float(confidence), 4),
        "status": status,
        "source": LISTING_SOURCE,
        "created_at": iso(utcnow()),
    }


@runtime_checkable
class FoodLinkAdapter(Protocol):
    """The integration contract. Four methods, per the brief."""

    mode: str

    def create_forecast_listing(self, listing: dict) -> dict:
        """Publish a predicted surplus as status='forecast'. No hard commitment."""
        ...

    def confirm_listing(self, listing_id: str, *, confirmed_qty: float | None = None, confirmed_by: str | None = None) -> dict:
        """Staff verified actual surplus. FoodLink's normal workflow may begin."""
        ...

    def withdraw_listing(self, listing_id: str, *, reason: str = "surplus_did_not_materialise") -> dict:
        """Sales caught up; release reservations and log the false alarm."""
        ...

    def get_listing_status(self, listing_id: str) -> dict:
        """Current status as FoodLink sees it."""
        ...


__all__ = [
    "FoodLinkAdapter",
    "FoodLinkError",
    "FoodLinkUnavailable",
    "ListingRejected",
    "canonical_listing",
]