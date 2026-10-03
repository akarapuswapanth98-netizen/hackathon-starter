"""Unit tests: the action ladder and its deterministic constraints."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.projects.foodlink_predict import actions as A
from app.projects.foodlink_predict import risk as R
from app.projects.foodlink_predict.config import ACTION_LADDER, SafetyConfig

NOW = _dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=_dt.timezone.utc)


def _safety(**over):
    base = dict(
        safe_windows_hours={"cooked": 24.0, "chilled": 48.0, "produce": 72.0, "packaged": 168.0},
        pickup_lead_time_hours=6.0,
        cold_start_days=14,
    )
    base.update(over)
    return SafetyConfig(**base)


class _Item:
    def __init__(self, price=60.0, cost=18.0):
        self.unit_price = price
        self.unit_cost = cost


class _Origin:
    id = "loc_a"
    lat = 17.3850
    lng = 78.4867


def _assessment(**over):
    payload = dict(
        batch_id="b1",
        item_id="i1",
        location_id="loc_a",
        item_name="Cooked Rice",
        food_class="cooked",
        computed_at=NOW,
        stock_qty=240.0,
        expected_demand={"p10": 40.0, "p50": 60.0, "p90": 80.0},
        expected_unsold=180.0,
        risk=0.85,
        urgency_hours=20.0,
        donate_by=NOW + _dt.timedelta(hours=20),
        priority=85.0,
        value_at_risk=180.0,
        status="critical",
        safe_to_donate=True,
        redistributable=True,
        horizon_days=1,
        insufficient_history=False,
        model_version="v1",
        demand_sigma=15.0,
        detail={"unit_cost": 18.0},
    )
    payload.update(over)
    return R.RiskAssessment(**payload)


DEST = [{"id": "loc_b", "name": "North Annex", "lat": 17.4500, "lng": 78.5000}]


def _ladder(assessment=None, *, destinations=DEST, deficit=None, recurring=0, item=None, rules=None):
    return A.rank_actions(
        assessment or _assessment(),
        item=item or _Item(),
        origin=_Origin(),
        destinations=destinations,
        deficit_by_location=deficit if deficit is not None else {"loc_b": 100.0},
        recurring_unsold_days=recurring,
        safety=_safety(),
        rules=rules or A.ActionRule(),
        now=NOW,
    )


def _by_action(ladder):
    return {c.action: c for c in ladder}


# ----------------------------------------------------------------- order --
def test_ladder_is_returned_in_recovery_hierarchy_order():
    assert [c.action for c in _ladder()] == list(ACTION_LADDER)


def test_every_candidate_carries_a_reason():
    for c in _ladder():
        assert c.reason, f"{c.action} has no explanation"


# -------------------------------------------------------- buy/prepare ----
def test_buy_prepare_less_blocked_below_the_recurring_threshold():
    c = _by_action(_ladder(recurring=1))["buy_prepare_less"]
    assert c.allowed is False
    assert "needs" in c.reason


def test_buy_prepare_less_allowed_for_recurring_over_supply():
    c = _by_action(_ladder(recurring=4))["buy_prepare_less"]
    assert c.allowed is True
    assert c.detail["applies_to"].startswith("next order")


def test_buy_prepare_less_names_the_future_scope():
    c = _by_action(_ladder(recurring=4))["buy_prepare_less"]
    assert "current stock" in c.detail["applies_to"]


# ------------------------------------------------------------- transfer --
def test_transfer_allowed_when_headroom_and_window_both_allow_it():
    c = _by_action(_ladder())["transfer"]
    assert c.allowed is True
    assert c.quantity > 0


def test_transfer_blocked_without_destination_headroom():
    c = _by_action(_ladder(deficit={"loc_b": 0.0}))["transfer"]
    assert c.allowed is False
    assert "headroom" in c.reason


def test_transfer_blocked_when_travel_exceeds_the_safety_window():
    tight = _assessment(urgency_hours=0.2, donate_by=NOW + _dt.timedelta(minutes=12))
    c = _by_action(_ladder(tight))["transfer"]
    assert c.allowed is False


def test_transfer_never_exceeds_stock_or_destination_need():
    c = _by_action(_ladder(deficit={"loc_b": 12.0}))["transfer"]
    assert c.quantity == pytest.approx(12.0)


def test_transfer_eta_is_labelled_estimated():
    c = _by_action(_ladder())["transfer"]
    assert "estimated" in c.detail["best_plan"]["eta_source"]


def test_transfer_without_coordinates_is_refused_not_guessed():
    blind = [{"id": "loc_b", "name": "Nowhere", "lat": 0.0, "lng": 0.0}]
    c = _by_action(_ladder(destinations=blind))["transfer"]
    assert c.allowed is False
    assert c.detail["options"][0]["eta_source"] == "unavailable"


def test_transfer_speed_is_configurable():
    fast = A.rank_actions(
        _assessment(urgency_hours=1.0, donate_by=NOW + _dt.timedelta(hours=1)),
        item=_Item(),
        origin=_Origin(),
        destinations=DEST,
        deficit_by_location={"loc_b": 50.0},
        recurring_unsold_days=0,
        safety=_safety(),
        rules=A.ActionRule(transport_kmh=200.0),
        now=NOW,
    )
    assert _by_action(fast)["transfer"].allowed is True


# ------------------------------------------------------------ promotion --
def test_promotion_blocked_at_high_risk():
    c = _by_action(_ladder(_assessment(risk=0.9)))["promotion"]
    assert c.allowed is False
    assert "will not clear" in c.reason


def test_promotion_blocked_below_the_band():
    c = _by_action(_ladder(_assessment(risk=0.1)))["promotion"]
    assert c.allowed is False


def test_promotion_blocked_without_enough_lead_time():
    tight = _assessment(risk=0.4, urgency_hours=2.0, donate_by=NOW + _dt.timedelta(hours=2))
    c = _by_action(_ladder(tight))["promotion"]
    assert c.allowed is False
    assert "markdown needs" in c.reason


def test_promotion_blocked_when_the_margin_is_negative():
    c = _by_action(_ladder(_assessment(risk=0.4), item=_Item(price=10.0, cost=20.0)))["promotion"]
    assert c.allowed is False
    assert "margin" in c.reason


def test_promotion_allowed_inside_the_band():
    mid = _assessment(risk=0.4, urgency_hours=30.0, donate_by=NOW + _dt.timedelta(hours=30))
    c = _by_action(_ladder(mid))["promotion"]
    assert c.allowed is True
    assert 0 < c.detail["suggested_discount_fraction"] <= 0.5


# --------------------------------------------------------------- donate --
def test_donate_allowed_at_high_risk():
    c = _by_action(_ladder())["donate"]
    assert c.allowed is True


def test_donate_blocked_for_a_non_redistributable_class():
    a = _assessment(food_class="???", safe_to_donate=False, redistributable=False)
    c = _by_action(_ladder(a))["donate"]
    assert c.allowed is False
    assert "not on the redistributable list" in c.reason


def test_donate_blocked_once_donate_by_has_passed():
    late = _assessment(urgency_hours=-1.0, donate_by=NOW - _dt.timedelta(hours=1), safe_to_donate=False)
    c = _by_action(_ladder(late))["donate"]
    assert c.allowed is False
    assert "already passed" in c.reason or "no longer" in c.reason


def test_donate_blocked_with_zero_stock():
    c = _by_action(_ladder(_assessment(stock_qty=0.0)))["donate"]
    assert c.allowed is False


def test_donate_confidence_hint_is_the_risk_score():
    c = _by_action(_ladder())["donate"]
    assert c.detail["confidence_hint"] == pytest.approx(0.85)


# -------------------------------------------------------------- compost --
def test_compost_blocked_while_the_window_is_open():
    c = _by_action(_ladder())["compost"]
    assert c.allowed is False
    assert "for people" in c.reason


def test_compost_allowed_after_donate_by_passes():
    late = _assessment(urgency_hours=-3.0, donate_by=NOW - _dt.timedelta(hours=3))
    c = _by_action(_ladder(late))["compost"]
    assert c.allowed is True
    assert c.detail["accounting"]


# ---------------------------------------------------- promo arithmetic ----
def test_promotion_math_caps_the_discount():
    m = A.promotion_math(qty=10, unit_price=100, unit_cost=50, discount_fraction=0.9, rules=A.ActionRule())
    assert m["applied_discount_fraction"] == 0.5
    assert m["discount_was_capped"] is True


def test_promotion_math_ignores_an_absurd_request():
    m = A.promotion_math(qty=10, unit_price=100, unit_cost=50, discount_fraction=5.0, rules=A.ActionRule())
    assert m["discount_fraction"] == 1.0
    assert m["applied_discount_fraction"] == 0.5


def test_promotion_math_computes_margin_at_the_discount():
    m = A.promotion_math(qty=10, unit_price=100, unit_cost=50, discount_fraction=0.25, rules=A.ActionRule())
    assert m["unit_price_after_discount"] == pytest.approx(75.0)
    assert m["margin_at_discount"] == pytest.approx(250.0)


def test_promotion_math_handles_a_full_discount():
    # The 50% cap applies, so a 100/60 item loses money on every unit.
    m = A.promotion_math(qty=10, unit_price=100, unit_cost=60, discount_fraction=1.0, rules=A.ActionRule())
    assert m["applied_discount_fraction"] == 0.5
    assert m["margin_at_discount"] < 0


# ------------------------------------------------------------- helpers ---
def test_allowed_actions_and_preferred_respect_the_order():
    ladder = _ladder(recurring=4)
    allowed = A.allowed_actions(ladder)
    assert allowed
    assert A.preferred(ladder) == allowed[0]


def test_dead_batch_falls_through_to_compost():
    """When no recovery step is legal, waste-stream handling is the only option."""
    dead = _assessment(
        food_class="???",
        safe_to_donate=False,
        redistributable=False,
        urgency_hours=-5.0,
        donate_by=NOW - _dt.timedelta(hours=5),
        stock_qty=0.0,
    )
    ladder = _ladder(dead, deficit={"loc_b": 0.0})
    assert A.preferred(ladder) == "compost"
    assert A.allowed_actions(ladder) == ["compost"]