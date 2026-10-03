"""Surplus listing lifecycle: create -> confirm -> withdraw.

This is the only module that talks to FoodLink, and it does so exclusively through
``adapters/``. Two gates protect it:

1. ``validators.validate`` must have passed for the recommendation being listed.
2. ``validators.can_publish_listing`` re-checks the live clock immediately before
   publishing, because a recommendation approved an hour ago may now be past its
   donate-by.

State transitions are enforced (``forecast -> confirmed|withdrawn``), duplicate
listings are rejected, and every adapter response is stored with its demo/simulated
flags so the UI can label it honestly.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from app.projects.foodlink_predict import impact as I
from app.projects.foodlink_predict import validators as V
from app.projects.foodlink_predict.adapters import FoodLinkError, canonical_listing, get_adapter
from app.projects.foodlink_predict.config import (
    ACTION_DONATE,
    LISTING_SOURCE,
    get_safety_config,
)
from app.projects.foodlink_predict.db import get_by_id, require_by_id, session_scope
from app.projects.foodlink_predict.errors import Conflict, Forbidden, SafetyViolation
from app.projects.foodlink_predict.models import (
    Batch,
    Item,
    Location,
    Recommendation,
    SurplusListing,
    WasteRisk,
    utcnow,
)
from app.projects.foodlink_predict.util import as_utc, iso, new_id, utcnow as _utcnow


def _load_context(org_id: str, batch_id: str) -> dict:
    with session_scope() as sess:
        batch = require_by_id(sess, Batch, batch_id, org_id, "Batch")
        item = require_by_id(sess, Item, batch.item_id, org_id, "Item")
        location = require_by_id(sess, Location, batch.location_id, org_id, "Location")
        risk_rows = [
            r
            for r in sess.query(WasteRisk).filter(WasteRisk.org_id == org_id, WasteRisk.batch_id == batch_id).all()
        ]
        latest_risk = risk_rows[-1] if risk_rows else None
        rec_rows = [
            r
            for r in sess.query(Recommendation)
            .filter(Recommendation.org_id == org_id, Recommendation.batch_id == batch_id)
            .order_by(Recommendation.created_at)
            .all()
        ]
        validated = [r for r in rec_rows if r.validation_status == "passed" and r.action == ACTION_DONATE]
        return {
            "batch": batch,
            "item": item,
            "location": location,
            "risk": latest_risk,
            "recommendation": validated[-1] if validated else None,
        }


def create_listing(
    org_id: str,
    *,
    batch_id: str,
    qty: float | None = None,
    confidence: float | None = None,
    now: _dt.datetime | None = None,
) -> dict:
    """Publish a FORECAST listing through the adapter."""
    ref = as_utc(now) or _utcnow()
    safety = get_safety_config()
    ctx = _load_context(org_id, batch_id)
    batch, item, location = ctx["batch"], ctx["item"], ctx["location"]
    rec = ctx["recommendation"]

    if rec is None:
        raise Forbidden(
            "No validated donate recommendation exists for this batch; run POST /api/recommend first. "
            "The validator must pass before a listing may be created."
        )

    q = float(qty if qty is not None else (rec.quantity or batch.qty))
    donate_by = as_utc(rec.deadline) or as_utc(batch.expires_at)

    # Forecast-listing confidence = P(the surplus materialises), which is exactly
    # what the risk engine computed: P(demand until expiry < stock). A high-risk
    # batch therefore carries HIGH confidence of surplus - the inverse would tell
    # FoodLink the batches most likely to need rescuing are the least certain,
    # which is the opposite of what the number means. Staff confirmation still
    # pins it to 1.0 because a verified quantity is no longer a prediction.
    risk_score = float(ctx["risk"].risk) if ctx["risk"] is not None else 0.0
    forecast_confidence = max(0.0, min(1.0, risk_score))

    payload = {
        "listing_id": new_id("lst"),
        "org_id": org_id,
        "location": {"id": location.id, "name": location.name, "lat": location.lat, "lng": location.lng, "timezone": location.timezone},
        "items": [
            {
                "item_id": item.id,
                "name": item.name,
                "category": item.category,
                "food_class": item.food_class,
                "qty": q,
                "qty_kg": round(q * float(item.unit_weight_kg or 0.35), 4),
                "unit": item.unit,
            }
        ],
        "ready_at": as_utc(batch.received_or_prepared_at),
        "donate_by": donate_by,
        "storage": batch.storage,
        "confidence": float(confidence if confidence is not None else forecast_confidence),
        "status": "forecast",
    }

    # Second gate: live clock re-check at publish time.
    gate = V.can_publish_listing(
        {
            "donate_by": donate_by,
            "expires_at": as_utc(batch.expires_at),
            "food_classes": [item.food_class],
            "qty": q,
            "items": payload["items"],
        },
        safety=safety,
        now=ref,
    )
    if not gate.passed:
        raise SafetyViolation(
            "Listing blocked by the safety validator",
            rule=gate.issues[0].rule,
            detail="; ".join(i.message for i in gate.issues),
        )

    adapter = get_adapter()
    try:
        response = adapter.create_forecast_listing(dict(payload))
    except FoodLinkError as exc:
        raise Conflict(f"FoodLink did not accept the forecast listing: {exc}", detail=exc.reason)

    with session_scope() as sess:
        row = SurplusListing(
            id=payload["listing_id"],
            org_id=org_id,
            recommendation_id=rec.id,
            location_id=location.id,
            lat=float(location.lat or 0.0),
            lng=float(location.lng or 0.0),
            items=payload["items"],
            ready_at=payload["ready_at"],
            donate_by=donate_by,
            storage=payload["storage"],
            confidence=payload["confidence"],
            status="forecast",
            source=LISTING_SOURCE,
            qty_kg=payload["items"][0]["qty_kg"],
            external_ref=str(response.get("external_ref") or "") or None,
        )
        sess.add(row)
        sess.flush()
        result = _listing_dict(row, adapter_response=response)

    result["validator"] = gate.to_dict()
    return result


def confirm_listing(
    org_id: str,
    *,
    listing_id: str,
    confirmed_qty: float | None = None,
    confirmed_by: str | None = None,
    record_impact: bool = True,
    now: _dt.datetime | None = None,
) -> dict:
    """Staff confirmed actual surplus. FoodLink's normal workflow may begin."""
    ref = as_utc(now) or _utcnow()
    with session_scope() as sess:
        row = require_by_id(sess, SurplusListing, listing_id, org_id, "Listing")
        if row.status != "forecast":
            raise Conflict(f"Listing is '{row.status}'; only a 'forecast' listing can be confirmed", detail=row.status)
        donate_by = as_utc(row.donate_by)

    # Re-check the clock: confirmation is the moment food becomes a real promise.
    if donate_by is None or donate_by <= ref:
        raise SafetyViolation(
            "Listing cannot be confirmed because its donate-by has passed",
            rule="donation_past_donate_by",
            detail=iso(donate_by),
        )

    qty = float(confirmed_qty) if confirmed_qty is not None else _listing_qty(org_id, listing_id)
    adapter = get_adapter()
    try:
        response = adapter.confirm_listing(listing_id, confirmed_qty=confirmed_qty, confirmed_by=confirmed_by)
    except FoodLinkError as exc:
        raise Conflict(f"FoodLink did not confirm the listing: {exc}", detail=exc.reason)

    with session_scope() as sess:
        row = require_by_id(sess, SurplusListing, listing_id, org_id, "Listing")
        row.status = "confirmed"
        row.confidence = 1.0
        row.updated_at = ref
        impact_event = None
        if record_impact:
            impact_event = _record_listing_impact(sess, org_id, row, qty, ref)
        result = _listing_dict(row, adapter_response=response)
        if impact_event is not None:
            result["impact"] = I.compute(
                action_type=ACTION_DONATE,
                qty=qty,
                unit_weight_kg=impact_event.detail.get("unit_weight_kg", 0.35),
                unit_cost=impact_event.detail.get("unit_cost", 0.0),
            ).to_dict()
    result["confirmed_qty"] = qty
    return result


def withdraw_listing(
    org_id: str,
    *,
    listing_id: str,
    reason: str = "surplus_did_not_materialise",
    now: _dt.datetime | None = None,
) -> dict:
    """Sales caught up: the surplus never materialised."""
    ref = as_utc(now) or _utcnow()
    with session_scope() as sess:
        row = require_by_id(sess, SurplusListing, listing_id, org_id, "Listing")
        if row.status == "withdrawn":
            raise Conflict("Listing is already withdrawn", detail=row.status)

    adapter = get_adapter()
    try:
        response = adapter.withdraw_listing(listing_id, reason=reason)
    except FoodLinkError as exc:
        raise Conflict(f"FoodLink did not withdraw the listing: {exc}", detail=exc.reason)

    with session_scope() as sess:
        row = require_by_id(sess, SurplusListing, listing_id, org_id, "Listing")
        row.status = "withdrawn"
        row.withdrawn_reason = reason
        row.confidence = 0.0
        row.updated_at = ref
        result = _listing_dict(row, adapter_response=response)
        result["false_alarm"] = True
        result["note"] = (
            "Recorded as a false alarm. No impact was booked, which is the correct outcome: "
            "food that was never surplus must not inflate impact numbers."
        )
    return result


def get_listing(org_id: str, listing_id: str, *, refresh: bool = False) -> dict:
    with session_scope() as sess:
        row = require_by_id(sess, SurplusListing, listing_id, org_id, "Listing")
        local = _listing_dict(row)
    if refresh:
        adapter = get_adapter()
        try:
            local["foodlink"] = adapter.get_listing_status(listing_id)
        except FoodLinkError as exc:
            local["foodlink_error"] = str(exc)
    return local


def list_listings(org_id: str, *, status: str | None = None, limit: int = 50) -> dict:
    from sqlalchemy import select

    with session_scope() as sess:
        stmt = select(SurplusListing).where(SurplusListing.org_id == org_id)
        if status:
            stmt = stmt.where(SurplusListing.status == status)
        rows = list(sess.execute(stmt.order_by(SurplusListing.created_at.desc()).limit(limit)).scalars().all())
        items = [_listing_dict(r) for r in rows]
        # Honest metric alongside the list: how often predictions were wrong.
        stats = I.false_alarm_stats(sess, org_id)
    return {"org_id": org_id, "count": len(items), "items": items, "false_alarm_stats": stats}


def _batch_id_for(sess, org_id: str, listing: SurplusListing) -> str | None:
    if not listing.recommendation_id:
        return None
    rec = get_by_id(sess, Recommendation, listing.recommendation_id, org_id)
    return rec.batch_id if rec else None


def _listing_qty(org_id: str, listing_id: str) -> float:
    with session_scope() as sess:
        row = require_by_id(sess, SurplusListing, listing_id, org_id, "Listing")
        items = row.items or []
        return float(items[0].get("qty", 0.0)) if items else 0.0


def _record_listing_impact(sess, org_id: str, listing: SurplusListing, qty: float, ref: _dt.datetime):
    items = listing.items or []
    if not items:
        return None
    item_id = items[0].get("item_id")
    item = get_by_id(sess, Item, item_id, org_id) if item_id else None
    if item is None:
        return None
    return I.record(
        sess,
        org_id=org_id,
        action_type=ACTION_DONATE,
        qty=qty,
        unit_weight_kg=float(item.unit_weight_kg or 0.35),
        unit_cost=float(item.unit_cost or 0.0),
        recommendation_id=listing.recommendation_id,
        location_id=listing.location_id,
        recorded_at=ref,
        detail={"listing_id": listing.id, "event": "listing_confirmed"},
    )


def _listing_dict(row: SurplusListing, *, adapter_response: dict | None = None) -> dict:
    out = {
        "listing_id": row.id,
        "org_id": row.org_id,
        "recommendation_id": row.recommendation_id,
        "location": {"id": row.location_id, "lat": row.lat, "lng": row.lng},
        "items": row.items or [],
        "ready_at": iso(row.ready_at),
        "donate_by": iso(row.donate_by),
        "storage": row.storage,
        "confidence": round(float(row.confidence or 0.0), 4),
        "status": row.status,
        "source": row.source,
        "qty_kg": round(float(row.qty_kg or 0.0), 4),
        "withdrawn_reason": row.withdrawn_reason,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
    if adapter_response is not None:
        out["foodlink"] = adapter_response
    return out


__all__ = ["confirm_listing", "create_listing", "get_listing", "list_listings", "withdraw_listing"]