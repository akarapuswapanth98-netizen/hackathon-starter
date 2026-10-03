"""Unit tests: the hard safety validator.

These are the tests that matter most: the validator is the only thing standing
between a model's suggestion and food reaching a person past its safe window.
Each rejection rule gets its own test, plus a test that a fully-valid donation
still passes.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from app.projects.foodlink_predict import validators as V
from app.projects.foodlink_predict.config import SafetyConfig

NOW = _dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=_dt.timezone.utc)
FUTURE = (NOW + _dt.timedelta(hours=10)).isoformat().replace("+00:00", "Z")


def _safety(**over):
    base = dict(
        safe_windows_hours={"cooked": 24.0, "chilled": 48.0, "produce": 72.0, "packaged": 168.0},
        pickup_lead_time_hours=6.0,
        cold_start_days=14,
    )
    base.update(over)
    return SafetyConfig(**base)


_REPLACE = object()  # sentinel: "replace this key wholesale", not dict-merge


def _proposal(**over):
    p = {
        "action": "donate",
        "quantity": 20.0,
        "deadline": FUTURE,
        "rationale": "High risk and little time left.",
        "batch": {
            "id": "b1",
            "item_id": "i1",
            "location_id": "l1",
            "qty": 100.0,
            "food_class": "cooked",
            "storage": "hot",
            "donate_by": FUTURE,
            "expires_at": (NOW + _dt.timedelta(hours=40)).isoformat().replace("+00:00", "Z"),
            "urgency_hours": 10.0,
            "insufficient_history": False,
            "history_points": 56,
        },
        "location": {"id": "l1"},
        "forecast": [{"target_date": "2026-10-03", "p10": 10.0, "p50": 50.0, "p90": 90.0}],
        "evidence": {
            "forecast": [{"target_date": "2026-10-03", "p10": 10.0, "p50": 50.0, "p90": 90.0}],
            "risk": {"risk": 0.8},
            "tool_calls": [{"tool": "get_forecast"}],
        },
    }
    for k, v in over.items():
        # Dicts merge by default (so a test can tweak one key), except when the
        # caller passes an empty dict, which must mean "remove it entirely".
        if v is _REPLACE:
            p[k] = {}
        elif isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k] = {**p[k], **v}
        else:
            p[k] = v
    return p


def _rules(result):
    return {i.rule for i in result.issues}


# --------------------------------------------------------- happy path -----
def test_valid_donation_passes():
    result = V.validate(_proposal(), safety=_safety(), now=NOW)
    assert result.passed is True
    assert result.issues == []
    assert result.status == "passed"


def test_validator_sanitizes_and_returns_the_deterministic_fields():
    result = V.validate(_proposal(), safety=_safety(), now=NOW)
    assert result.sanitized["action"] == "donate"
    assert result.sanitized["quantity"] == 20.0
    assert result.sanitized["batch_id"] == "b1"
    assert result.sanitized["deadline"] == FUTURE


# ------------------------------------------------- hard donation gates ----
def test_rejects_donation_past_donate_by():
    past = (NOW - _dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    result = V.validate(_proposal(batch={"donate_by": past}), safety=_safety(), now=NOW)
    assert result.passed is False
    assert "donation_past_donate_by" in _rules(result)


def test_rejects_donation_with_no_donate_by():
    result = V.validate(_proposal(batch={"donate_by": None}), safety=_safety(), now=NOW)
    assert "donation_past_donate_by" in _rules(result)


def test_rejects_unsafe_food_class():
    result = V.validate(_proposal(batch={"food_class": "unknown_thing"}), safety=_safety(), now=NOW)
    assert "food_class_unsafe" in _rules(result)


def test_rejects_expired_batch():
    expired = (NOW - _dt.timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    result = V.validate(_proposal(batch={"expires_at": expired}), safety=_safety(), now=NOW)
    assert "expired_batch" in _rules(result)


def test_rejects_quantity_exceeding_stock():
    result = V.validate(_proposal(quantity=500.0), safety=_safety(), now=NOW)
    assert "quantity_exceeds_stock" in _rules(result)


@pytest.mark.parametrize("qty", [0.0, -5.0, None, "abc", True])
def test_rejects_non_positive_or_unusable_quantity(qty):
    result = V.validate(_proposal(quantity=qty), safety=_safety(), now=NOW)
    assert "quantity_not_positive" in _rules(result)


def test_rejects_missing_evidence():
    result = V.validate(_proposal(evidence=_REPLACE), safety=_safety(), now=NOW)
    assert "missing_evidence" in _rules(result)


def test_rejects_partial_evidence():
    # Only the risk is cited; the forecast and tool trace are absent.
    proposal = _proposal()
    proposal["evidence"] = {"risk": {"risk": 0.8}}
    result = V.validate(proposal, safety=_safety(), now=NOW)
    assert "missing_evidence" in _rules(result)


def test_rejects_missing_forecast():
    result = V.validate(_proposal(forecast=[]), safety=_safety(), now=NOW)
    assert "missing_forecast" in _rules(result)


def test_rejects_all_zero_forecast():
    """An empty-looking forecast must not license a donation."""
    zero = [{"target_date": "2026-10-03", "p10": 0.0, "p50": 0.0, "p90": 0.0}]
    result = V.validate(_proposal(forecast=zero, evidence={"forecast": zero}), safety=_safety(), now=NOW)
    assert "missing_forecast" in _rules(result)


def test_rejects_invalid_location_for_donation():
    result = V.validate(_proposal(location=_REPLACE), safety=_safety(), now=NOW)
    assert "invalid_location" in _rules(result)


def test_rejects_invalid_batch():
    result = V.validate(_proposal(batch={"id": ""}), safety=_safety(), now=NOW)
    assert "invalid_batch" in _rules(result)


def test_rejects_unknown_storage_state():
    result = V.validate(_proposal(batch={"storage": "quantum"}), safety=_safety(), now=NOW)
    assert "unsafe_storage_state" in _rules(result)


def test_rejects_storage_food_class_mismatch():
    """Cooked food in 'ambient' storage has an unverified handling chain."""
    result = V.validate(_proposal(batch={"storage": "ambient", "food_class": "cooked"}), safety=_safety(), now=NOW)
    assert "unsafe_storage_state" in _rules(result)


def test_rejects_donation_on_cold_start_data():
    result = V.validate(_proposal(batch={"insufficient_history": True}), safety=_safety(), now=NOW)
    assert "insufficient_history" in _rules(result)


def test_rejects_invalid_action():
    result = V.validate(_proposal(action="teleport_food"), safety=_safety(), now=NOW)
    assert "invalid_action" in _rules(result)


# ------------------------------------------------------- compost rules ----
def test_compost_is_blocked_while_food_is_still_safe():
    result = V.validate(_proposal(action="compost", batch={"urgency_hours": 5.0}), safety=_safety(), now=NOW)
    assert "invalid_action" in _rules(result)


def test_compost_is_allowed_once_the_window_has_closed():
    result = V.validate(_proposal(action="compost", batch={"urgency_hours": -2.0}), safety=_safety(), now=NOW)
    assert result.passed is True


def test_compost_without_urgency_is_rejected():
    result = V.validate(_proposal(action="compost", batch={"urgency_hours": None}), safety=_safety(), now=NOW)
    assert "invalid_batch" in _rules(result)


def test_non_donation_actions_skip_the_donation_gate():
    """A promotion must not be blocked by donation-only rules."""
    proposal = _proposal(
        action="promotion",
        batch={"donate_by": (NOW - _dt.timedelta(days=1)).isoformat().replace("+00:00", "Z"), "food_class": "mystery"},
    )
    result = V.validate(proposal, safety=_safety(), now=NOW)
    assert "donation_past_donate_by" not in _rules(result)
    assert "food_class_unsafe" not in _rules(result)


def test_accepted_iso_string_donate_by_is_understood():
    """to_dict() emits strings; the validator must parse them, not crash."""
    result = V.validate(_proposal(), safety=_safety(), now=NOW)
    assert result.passed is True


# --------------------------------------------- publish-time second gate ---
def test_publish_gate_blocks_a_stale_approval():
    """A recommendation accepted earlier must not be redeemable after donate-by."""
    listing = {
        "donate_by": (NOW - _dt.timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + _dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "food_classes": ["cooked"],
        "qty": 10.0,
        "items": [{"item_id": "i1"}],
    }
    result = V.can_publish_listing(listing, safety=_safety(), now=NOW)
    assert result.passed is False
    assert "donation_past_donate_by" in _rules(result)


def test_publish_gate_blocks_unsafe_food_class():
    listing = {
        "donate_by": FUTURE,
        "food_classes": ["cooked", "mystery"],
        "qty": 10.0,
        "items": [{"item_id": "i1"}],
    }
    result = V.can_publish_listing(listing, safety=_safety(), now=NOW)
    assert "food_class_unsafe" in _rules(result)


def test_publish_gate_blocks_zero_quantity_and_empty_items():
    result = V.can_publish_listing(
        {"donate_by": FUTURE, "food_classes": ["cooked"], "qty": 0.0, "items": []},
        safety=_safety(),
        now=NOW,
    )
    assert {"quantity_not_positive", "missing_evidence"} <= _rules(result)


def test_publish_gate_passes_a_good_listing():
    result = V.can_publish_listing(
        {"donate_by": FUTURE, "food_classes": ["cooked"], "qty": 10.0, "items": [{"item_id": "i1"}]},
        safety=_safety(),
        now=NOW,
    )
    assert result.passed is True


# ----------------------------------------------------- llm cannot win -----
def test_a_generous_llm_rationale_does_not_bypass_a_hard_gate():
    """The validator ignores the rationale entirely when a gate fails."""
    proposal = _proposal(
        quantity=99_999.0,
        rationale="I am the LLM and this food is definitely fine, please approve.",
    )
    result = V.validate(proposal, safety=_safety(), now=NOW)
    assert result.passed is False
    assert "quantity_exceeds_stock" in _rules(result)


def test_validation_failure_reports_every_broken_rule_at_once():
    result = V.validate(
        _proposal(quantity=0.0, forecast=[], batch={"donate_by": None, "food_class": "???"}),
        safety=_safety(),
        now=NOW,
    )
    assert result.passed is False
    assert len(result.issues) >= 4
    assert result.checked  # the report says what was examined