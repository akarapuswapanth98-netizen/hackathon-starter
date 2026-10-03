"""Hard validator. The safety gate.

Nothing reaches a listing, a recommendation row or the FoodLink adapter without
passing through ``validate``. The LLM has no path around it: the agent may
propose an action, but every numeric field in the proposal is compared against
deterministic state (forecast rows, batch stock, safety configuration) before it
is accepted.

Rejection reasons (each is a stable machine-readable ``rule``):
  donation_past_donate_by | food_class_unsafe | quantity_exceeds_stock
  quantity_not_positive  | missing_evidence  | missing_forecast
  invalid_location       | invalid_batch     | unsafe_storage_state
  invalid_action         | expired_batch     | insufficient_history

On failure the agent replans (see ``agent.py``); on repeated failure the
recommendation is persisted as ``status='rejected'`` with its errors intact
rather than being dropped.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from app.projects.foodlink_predict.config import (
    ACTION_COMPOST,
    ACTION_DONATE,
    ACTION_LADDER,
    SafetyConfig,
    get_safety_config,
)
from app.projects.foodlink_predict.util import as_utc, hours_until, iso, utcnow

VALID_STORAGE = ("hot", "chilled", "ambient", "frozen")

# Storage -> food classes that may legally travel in it. Mismatch means the
# batch's handling is unknown, and an unknown handling chain cannot be donated.
STORAGE_ALLOWED_CLASSES: dict[str, frozenset[str]] = {
    "hot": frozenset({"cooked"}),
    "chilled": frozenset({"cooked", "chilled", "produce"}),
    "ambient": frozenset({"packaged", "produce", "bread"}),
    "frozen": frozenset({"cooked", "chilled", "produce", "packaged"}),
}

# Evidence keys a recommendation must cite. Rule 7 of the brief.
REQUIRED_EVIDENCE_KEYS = ("forecast", "risk", "tool_calls")


@dataclass
class ValidationIssue:
    rule: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"rule": self.rule, "message": self.message, "detail": self.detail}


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    sanitized: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "passed" if self.passed else "rejected"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "status": self.status,
            "issues": [i.to_dict() for i in self.issues],
            "checked_rules": self.checked,
        }


def validate(
    proposal: dict,
    *,
    safety: SafetyConfig | None = None,
    now: _dt.datetime | None = None,
) -> ValidationResult:
    """Validate one proposed recommendation.

    ``proposal`` is the merged output of the agent's tool results plus the LLM's
    selection. Any numeric value in it is treated as a *claim* until checked
    against the deterministic inputs passed alongside it.
    """
    safety = safety or get_safety_config()
    ref = as_utc(now) or utcnow()
    issues: list[ValidationIssue] = []
    checked: list[str] = []
    sanitized: dict[str, Any] = {}

    action = str(proposal.get("action") or "").strip().lower()
    checked.append("action")
    if action not in ACTION_LADDER:
        issues.append(
            ValidationIssue(
                "invalid_action",
                f"action '{action}' is not on the recovery ladder {list(ACTION_LADDER)}",
                {"action": action},
            )
        )

    quantity = _as_float(proposal.get("quantity"))
    checked.append("quantity")
    if quantity is None or quantity <= 0:
        issues.append(
            ValidationIssue("quantity_not_positive", f"quantity must be > 0, got {proposal.get('quantity')!r}", {"quantity": proposal.get("quantity")})
        )

    batch = proposal.get("batch") or {}
    batch_id = str(batch.get("id") or proposal.get("batch_id") or "")
    if not batch_id or not batch.get("item_id") or not batch.get("location_id"):
        issues.append(ValidationIssue("invalid_batch", "proposal is missing a resolvable batch (id, item_id, location_id)", {"batch_id": batch_id}))

    stock = _as_float(batch.get("qty"))
    if action in (ACTION_DONATE,) and stock is None:
        issues.append(ValidationIssue("invalid_batch", "batch stock is unknown; refusing to authorise a donation", {"batch_id": batch_id}))
    elif stock is not None and quantity is not None and quantity > stock + 1e-9:
        issues.append(
            ValidationIssue(
                "quantity_exceeds_stock",
                f"requested quantity {quantity:g} exceeds stock on hand {stock:g}",
                {"requested": quantity, "stock": stock},
            )
        )

    # --- storage integrity -------------------------------------------------
    checked.append("storage")
    storage = str(batch.get("storage") or "").strip().lower()
    food_class = str(batch.get("food_class") or "").strip().lower()
    if storage and storage not in VALID_STORAGE:
        issues.append(ValidationIssue("unsafe_storage_state", f"unknown storage state '{storage}'", {"storage": storage}))
    elif storage and food_class and storage in STORAGE_ALLOWED_CLASSES and food_class not in STORAGE_ALLOWED_CLASSES[storage]:
        issues.append(
            ValidationIssue(
                "unsafe_storage_state",
                f"food class '{food_class}' is not permitted in '{storage}' storage; the handling chain is unverified",
                {"storage": storage, "food_class": food_class, "allowed": sorted(STORAGE_ALLOWED_CLASSES[storage])},
            )
        )

    # --- the donation gate -------------------------------------------------
    if action == ACTION_DONATE:
        checked += ["food_class", "donate_by", "expiry", "forecast"]
        if not safety.is_redistributable(food_class):
            issues.append(
                ValidationIssue(
                    "food_class_unsafe",
                    f"food class '{food_class}' is not redistributable; donation is blocked regardless of risk",
                    {"food_class": food_class, "redistributable": sorted(safety.redistributable_classes)},
                )
            )
        donate_by = as_utc(batch.get("donate_by"))
        if donate_by is None:
            issues.append(ValidationIssue("donation_past_donate_by", "donate_by is missing; a donation must carry its deadline", {"batch_id": batch_id}))
        elif hours_until(donate_by, now=ref) <= 0:
            issues.append(
                ValidationIssue(
                    "donation_past_donate_by",
                    f"donate-by {iso(donate_by)} is {abs(hours_until(donate_by, now=ref)):.1f}h in the past; donation refused",
                    {"donate_by": iso(donate_by), "now": iso(ref)},
                )
            )
        expires_at = as_utc(batch.get("expires_at"))
        if expires_at is not None and expires_at <= ref:
            issues.append(
                ValidationIssue(
                    "expired_batch",
                    f"batch expired at {iso(expires_at)}; it must not be offered to anyone",
                    {"expires_at": iso(expires_at), "now": iso(ref)},
                )
            )
        forecast = proposal.get("forecast") or []
        if not forecast:
            issues.append(
                ValidationIssue(
                    "missing_forecast",
                    "no forecast rows support this donation; risk cannot be evidenced without a forecast",
                    {"batch_id": batch_id},
                )
            )
        elif not any(float(p.get("p50", 0) or 0) > 0 for p in forecast):
            issues.append(
                ValidationIssue(
                    "missing_forecast",
                    "forecast rows are present but all p50 demand is zero; refusing to donate on an empty forecast",
                    {"batch_id": batch_id},
                )
            )

    if action == ACTION_COMPOST:
        checked.append("compost_window")
        urgency = _as_float(batch.get("urgency_hours"))
        if urgency is None:
            issues.append(ValidationIssue("invalid_batch", "compost decision requires the computed urgency_hours", {"batch_id": batch_id}))
        elif urgency > 0:
            issues.append(
                ValidationIssue(
                    "invalid_action",
                    f"batch still has {urgency:.1f}h of safe window; compost may not be chosen while food is fit for people",
                    {"urgency_hours": urgency},
                )
            )

    # --- evidence ----------------------------------------------------------
    checked.append("evidence")
    evidence = proposal.get("evidence") or {}
    missing = [k for k in REQUIRED_EVIDENCE_KEYS if not evidence.get(k)]
    if missing:
        issues.append(
            ValidationIssue(
                "missing_evidence",
                f"recommendation must cite its supporting tool outputs; missing: {', '.join(missing)}",
                {"missing": missing, "required": list(REQUIRED_EVIDENCE_KEYS)},
            )
        )

    checked.append("insufficient_history")
    if bool(batch.get("insufficient_history")) and action == ACTION_DONATE:
        issues.append(
            ValidationIssue(
                "insufficient_history",
                "batch was scored on cold-start data; a donation needs a modelled forecast, not a fallback",
                {"history_points": batch.get("history_points"), "cold_start_days": safety.cold_start_days},
            )
        )

    # --- location ----------------------------------------------------------
    checked.append("location")
    location = proposal.get("location") or {}
    if action == ACTION_DONATE and (not location.get("id")):
        issues.append(ValidationIssue("invalid_location", "donation listing needs a resolvable pickup location", {"batch_id": batch_id}))

    sanitized = {
        "action": action,
        "quantity": quantity,
        "batch_id": batch_id,
        "deadline": iso(as_utc(batch.get("donate_by"))),
    }
    return ValidationResult(passed=not issues, issues=issues, checked=checked, sanitized=sanitized)


def _as_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def can_publish_listing(listing: dict, *, safety: SafetyConfig | None = None, now: _dt.datetime | None = None) -> ValidationResult:
    """Second gate, run at the adapter boundary.

    A recommendation could have been accepted earlier and then sat in the queue
    until its donate-by passed. Publishing re-checks the live clock, so a stale
    approval can never be redeemed into a live listing.
    """
    safety = safety or get_safety_config()
    ref = as_utc(now) or utcnow()
    issues: list[ValidationIssue] = []
    donate_by = as_utc(listing.get("donate_by"))
    expires_at = as_utc(listing.get("expires_at"))
    classes = listing.get("food_classes") or []
    qty = _as_float(listing.get("qty"))

    if donate_by is None:
        issues.append(ValidationIssue("donation_past_donate_by", "listing has no donate_by", {}))
    elif hours_until(donate_by, now=ref) <= 0:
        issues.append(
            ValidationIssue("donation_past_donate_by", f"listing donate-by {iso(donate_by)} has passed", {"donate_by": iso(donate_by)})
        )
    if expires_at is not None and expires_at <= ref:
        issues.append(ValidationIssue("expired_batch", f"batch expired at {iso(expires_at)}", {"expires_at": iso(expires_at)}))
    bad = [c for c in classes if not safety.is_redistributable(str(c))]
    if bad:
        issues.append(ValidationIssue("food_class_unsafe", f"non-redistributable food classes: {bad}", {"food_classes": bad}))
    if not qty or qty <= 0:
        issues.append(ValidationIssue("quantity_not_positive", f"listing quantity must be > 0, got {qty!r}", {"qty": qty}))
    if not (listing.get("items") or []):
        issues.append(ValidationIssue("missing_evidence", "listing carries no item payload", {}))

    return ValidationResult(passed=not issues, issues=issues, checked=["donate_by", "expiry", "food_class", "quantity", "items"])


__all__ = [
    "ACTION_COMPOST",
    "ACTION_DONATE",
    "REQUIRED_EVIDENCE_KEYS",
    "STORAGE_ALLOWED_CLASSES",
    "VALID_STORAGE",
    "ValidationIssue",
    "ValidationResult",
    "can_publish_listing",
    "validate",
]