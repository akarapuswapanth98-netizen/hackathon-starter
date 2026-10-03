"""Offline demo implementation of the FoodLink adapter.

What this does: stores listings in memory and simulates FoodLink *receiving*
them, so the end-to-end demo runs with no network and no credentials.

What this does NOT do: it does not run FoodLink's detect / match / negotiate /
hand off / deliver / verify agents. Those live in a system this module has never
been given access to. Every returned payload is therefore stamped:

    demo=True, simulated=True, executed_by="demo-simulator"

so a demo screen cannot be mistaken for a real rescue. ``simulated_event``
describes what a real FoodLink *would* be expected to do next, and is labelled
as an expectation, not a result.
"""

from __future__ import annotations

import threading
from typing import Any

from app.projects.foodlink_predict.adapters.base import (
    FoodLinkError,
    FoodLinkUnavailable,
    ListingRejected,
    canonical_listing,
)
from app.projects.foodlink_predict.util import utcnow

# Allowed state machine. Mirrors the PDF's status table.
_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "forecast": ("confirmed", "withdrawn"),
    "confirmed": ("withdrawn",),
    "withdrawn": (),
}

# What a real FoodLink Detect agent is expected to do per status, per PDF s.5.
_EXPECTED_FOODLINK_BEHAVIOUR: dict[str, str] = {
    "forecast": "Detect pre-warns NGOs and volunteers; no commitments are made yet.",
    "confirmed": "Full detect -> match -> negotiate -> hand off -> deliver -> verify flow begins.",
    "withdrawn": "Soft reservations are released and the avoided false alarm is logged.",
}


class DemoFoodLinkAdapter:
    """In-memory FoodLink stand-in. Deterministic and clearly labelled."""

    mode = "demo"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, dict] = {}
        self._events: list[dict] = []
        # Test/demo hook: flip to exercise the "FoodLink unavailable" branch.
        self._force_unavailable = False

    def _check_available(self) -> None:
        if self._force_unavailable:
            raise FoodLinkUnavailable(
                "FoodLink is unavailable (demo adapter forced offline)", reason="foodlink_unavailable", status_code=503
            )

    # -- helpers ----------------------------------------------------------
    def _envelope(self, listing_id: str, extra: dict | None = None) -> dict:
        rec = self._store.get(listing_id)
        if rec is None:
            raise FoodLinkUnavailable(f"FoodLink has no listing '{listing_id}'", reason="not_found", status_code=404)
        return {
            "listing_id": listing_id,
            "status": rec["status"],
            "confidence": rec["confidence"],
            "source": rec["source"],
            "received_at": rec["received_at"],
            "updated_at": rec["updated_at"],
            "mode": self.mode,
            "demo": True,
            "simulated": True,
            "executed_by": "demo-simulator",
            "real_foodlink_executed": False,
            "expected_foodlink_behaviour": _EXPECTED_FOODLINK_BEHAVIOUR.get(rec["status"], ""),
            "note": "Simulated FoodLink receipt. No FoodLink agent ran and no data left this process.",
            **(extra or {}),
        }

    def _transition(self, listing_id: str, target: str, patch: dict | None = None, **kwargs: Any) -> dict:
        with self._lock:
            if listing_id not in self._store:
                raise FoodLinkUnavailable(f"FoodLink has no listing '{listing_id}'", reason="not_found", status_code=404)
            rec = self._store[listing_id]
            current = rec["status"]
            if target not in _TRANSITIONS[current]:
                raise ListingRejected(
                    f"cannot move listing '{listing_id}' from '{current}' to '{target}'",
                    reason="invalid_transition",
                )
            rec["status"] = target
            rec["updated_at"] = utcnow().isoformat()
            rec.update(patch or {})
            rec.update(kwargs)
            self._events.append({"listing_id": listing_id, "to": target, "at": rec["updated_at"]})
            return self._envelope(listing_id)

    # -- interface --------------------------------------------------------
    def create_forecast_listing(self, listing: dict) -> dict:
        self._check_available()
        doc = canonical_listing(**listing) if "contract_version" not in listing else dict(listing)
        listing_id = str(doc.get("listing_id") or "")
        if not listing_id:
            raise ListingRejected("listing_id is required", reason="missing_listing_id")
        if not doc.get("items"):
            raise ListingRejected("listing carries no items", reason="empty_items")
        with self._lock:
            existing = self._store.get(listing_id)
            if existing is not None:
                # Idempotent re-publish: return what FoodLink already holds.
                if existing["content_hash"] != _hash(doc):
                    raise ListingRejected(
                        f"listing '{listing_id}' already exists with different contents",
                        reason="duplicate_listing_conflict",
                    )
                return self._envelope(listing_id, {"duplicate": True})
            now = utcnow().isoformat()
            self._store[listing_id] = {
                **{k: v for k, v in doc.items() if k != "contract_version"},
                "status": doc.get("status", "forecast"),
                "confidence": float(doc.get("confidence", 0.0)),
                "source": doc.get("source", "waste-predictor"),
                "received_at": now,
                "updated_at": now,
                "content_hash": _hash(doc),
                "history": [{"status": doc.get("status", "forecast"), "at": now}],
            }
            return self._envelope(listing_id, {"duplicate": False})

    def confirm_listing(self, listing_id: str, *, confirmed_qty: float | None = None, confirmed_by: str | None = None) -> dict:
        self._check_available()
        patch: dict[str, Any] = {}
        if confirmed_qty is not None:
            if confirmed_qty <= 0:
                raise ListingRejected("confirmed_qty must be > 0", reason="invalid_qty")
            patch["confirmed_qty"] = float(confirmed_qty)
        # A confirmed listing is a real commitment: confidence becomes certain.
        patch["confidence"] = 1.0
        if confirmed_by:
            patch["confirmed_by"] = confirmed_by
        return self._transition(listing_id, "confirmed", patch)

    def withdraw_listing(self, listing_id: str, *, reason: str = "surplus_did_not_materialise") -> dict:
        self._check_available()
        return self._transition(listing_id, "withdrawn", {"withdrawn_reason": reason, "confidence": 0.0})

    def get_listing_status(self, listing_id: str) -> dict:
        self._check_available()
        with self._lock:
            return self._envelope(listing_id)

    # -- demo-only introspection ----------------------------------------
    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def listing_count(self) -> int:
        with self._lock:
            return len(self._store)

    def reset(self) -> None:
        with self._lock:
            self._store.clear()
            self._events.clear()

    def simulate_unavailable(self, flag: bool = True) -> None:
        """Test/demo hook: force the 'FoodLink is down' branch."""
        self._force_unavailable = bool(flag)


def _hash(doc: dict) -> str:
    import hashlib
    import json

    payload = {k: v for k, v in doc.items() if k not in ("created_at",)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


__all__ = ["DemoFoodLinkAdapter"]