"""Unit tests: waste risk, urgency, donate-by, safety windows, priority ranking."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.projects.foodlink_predict import risk as R
from app.projects.foodlink_predict.config import SafetyConfig

NOW = _dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=_dt.timezone.utc)


def _safety(**over):
    base = dict(
        safe_windows_hours={"cooked": 24.0, "chilled": 48.0, "produce": 72.0, "packaged": 168.0},
        pickup_lead_time_hours=6.0,
        cold_start_days=14,
    )
    base.update(over)
    return SafetyConfig(**base)


def _input(**over):
    payload = dict(
        batch_id="b1",
        org_id="o1",
        item_id="i1",
        location_id="l1",
        item_name="Cooked Rice",
        food_class="cooked",
        unit_cost=18.0,
        qty=240.0,
        prepared_at=NOW - _dt.timedelta(hours=5),
        expires_at=NOW + _dt.timedelta(hours=15),
        storage="hot",
        forecast=[],
        model_version="v1",
        history_points=56,
        method="model",
    )
    payload.update(over)
    return R.RiskInput(**payload)


def _fc(p50, spread=20.0, days=1):
    start = NOW.date()
    return [
        {"target_date": start + _dt.timedelta(days=i), "p10": p50 - spread, "p50": p50, "p90": p50 + spread}
        for i in range(days)
    ]


# --------------------------------------------------------- donate-by ------
def test_donate_by_is_not_expiry_and_leads_pickup_time():
    """The core safety property: donate_by < expiry, minus the pickup lead time."""
    safety = _safety()
    db = R.compute_donate_by(
        prepared_at=NOW - _dt.timedelta(hours=5),
        expires_at=NOW + _dt.timedelta(hours=15),
        food_class="cooked",
        safety=safety,
    )
    # Expiry (21:00) binds before the 24h cooked window (01:00 next day);
    # donate-by is then 6h earlier to leave room for FoodLink pickup -> 15:00.
    assert db == NOW + _dt.timedelta(hours=9)
    assert db < NOW + _dt.timedelta(hours=15)  # strictly before expiry


def test_donate_by_uses_the_shorter_of_window_and_expiry():
    safety = _safety()
    # Expiry (2h away) is sooner than the 24h cooked window.
    db = R.compute_donate_by(
        prepared_at=NOW - _dt.timedelta(hours=1),
        expires_at=NOW + _dt.timedelta(hours=2),
        food_class="cooked",
        safety=safety,
    )
    assert db == NOW - _dt.timedelta(hours=4)


def test_donate_by_uses_the_class_specific_window():
    cooked = R.compute_donate_by(
        prepared_at=NOW, expires_at=NOW + _dt.timedelta(days=30), food_class="cooked", safety=_safety()
    )
    packaged = R.compute_donate_by(
        prepared_at=NOW, expires_at=NOW + _dt.timedelta(days=30), food_class="packaged", safety=_safety()
    )
    assert cooked < packaged


def test_unknown_food_class_gets_the_most_conservative_window():
    """An unmapped class must never inherit a generous window."""
    safety = _safety()
    db = R.compute_donate_by(
        prepared_at=NOW, expires_at=NOW + _dt.timedelta(days=30), food_class="mystery", safety=safety
    )
    shortest = min(safety.safe_windows_hours.values())
    assert db == NOW + _dt.timedelta(hours=shortest - safety.pickup_lead_time_hours)


def test_invalid_safety_window_is_rejected():
    with pytest.raises(ValueError):
        _safety(safe_windows_hours={"cooked": -5.0}).validate()
    with pytest.raises(ValueError):
        _safety(safe_windows_hours={}).validate()
    with pytest.raises(ValueError):
        _safety(pickup_lead_time_hours=-1).validate()


def test_donate_by_raises_on_inverted_expiry():
    with pytest.raises(R.InvalidSafetyWindow):
        R.compute_donate_by(
            prepared_at=NOW,
            expires_at=NOW - _dt.timedelta(hours=1),
            food_class="cooked",
            safety=_safety(),
        )


def test_donate_by_rejects_a_non_positive_window():
    """A zero/negative window is a configuration error, not a usable date."""
    bad = SafetyConfig(safe_windows_hours={"cooked": 0.0}, pickup_lead_time_hours=0.0)
    with pytest.raises(ValueError):
        R.compute_donate_by(prepared_at=NOW, expires_at=NOW + _dt.timedelta(hours=5), food_class="cooked", safety=bad)


def test_donate_by_guards_its_own_window_invariant(monkeypatch):
    """Even a config that passes validate() is re-checked before use."""
    safety = _safety()
    # Simulate a provider that hands back a zero window despite validation.
    monkeypatch.setattr(type(safety), "window_for", lambda self, cls: 0.0)
    with pytest.raises(R.InvalidSafetyWindow):
        R.compute_donate_by(
            prepared_at=NOW, expires_at=NOW + _dt.timedelta(hours=5), food_class="cooked", safety=safety
        )


# ------------------------------------------------------------ statistics --
def test_probability_is_bounded_and_never_certain():
    assert 0.0 < R.probability_demand_below(1e9, 10.0, 1.0) < 1.0
    assert 0.0 < R.probability_demand_below(0.0, 10.0, 1.0) < 1.0


def test_probability_increases_with_stock():
    assert R.probability_demand_below(50, 100, 20) < R.probability_demand_below(200, 100, 20)


def test_day_sigma_has_a_relative_floor():
    """A zero-width band must not imply certainty."""
    assert R.day_sigma(100.0, 100.0, 100.0) == pytest.approx(100.0 * R.MIN_RELATIVE_SIGMA)


def test_aggregate_demand_sums_days_and_accumulates_sigma():
    pts = _fc(50.0, spread=25.6, days=3)
    agg = R.aggregate_demand(pts)
    assert agg["p50"] == pytest.approx(150.0)
    # Independent-day sigma grows faster than linearly in the number of days.
    assert agg["sigma"] > R.day_sigma(25.4, 50.0, 74.6)
    assert agg["days"] == 3


def test_aggregate_demand_handles_no_forecast():
    agg = R.aggregate_demand([])
    assert agg == {"p10": 0.0, "p50": 0.0, "p90": 0.0, "sigma": 0.0, "days": 0}


# ---------------------------------------------------------------- assess --
def test_normal_batch_low_risk():
    a = R.assess(_input(qty=50.0, forecast=_fc(200.0, spread=30.0, days=2)), safety=_safety(), now=NOW)
    assert a.expected_unsold == 0.0
    assert a.risk < 0.25
    assert a.status == "low"
    assert a.safe_to_donate is True


def test_high_risk_batch_with_tight_window():
    a = R.assess(_input(qty=240.0, forecast=_fc(60.0, spread=15.0, days=1)), safety=_safety(), now=NOW)
    assert a.expected_unsold == pytest.approx(180.0)
    assert a.risk > 0.75
    assert a.status in ("critical", "expired")
    assert a.safe_to_donate is True


def test_expired_batch_is_never_safe_to_donate():
    a = R.assess(
        _input(expires_at=NOW - _dt.timedelta(hours=2), forecast=_fc(10.0)), safety=_safety(), now=NOW
    )
    assert a.status == "expired"
    assert a.safe_to_donate is False
    assert a.urgency_hours < 0


def test_almost_expired_batch_has_small_urgency():
    a = R.assess(
        _input(prepared_at=NOW - _dt.timedelta(hours=23), expires_at=NOW + _dt.timedelta(minutes=30), forecast=_fc(300.0)),
        safety=_safety(),
        now=NOW,
    )
    assert a.urgency_hours < 0
    assert a.safe_to_donate is False


def test_zero_stock_has_no_exposure():
    a = R.assess(_input(qty=0.0, forecast=_fc(10.0)), safety=_safety(), now=NOW)
    assert a.stock_qty == 0.0
    assert a.expected_unsold == 0.0
    assert a.value_at_risk == 0.0
    assert a.priority == 0.0


def test_insufficient_history_is_flagged():
    a = R.assess(_input(history_points=3, forecast=_fc(10.0)), safety=_safety(), now=NOW)
    assert a.insufficient_history is True
    a2 = R.assess(_input(history_points=56, forecast=_fc(10.0)), safety=_safety(), now=NOW)
    assert a2.insufficient_history is False


def test_non_redistributable_class_is_not_safe_to_donate():
    a = R.assess(
        _input(food_class="unknown_class", forecast=_fc(10.0)),
        safety=_safety(),
        now=NOW,
    )
    assert a.redistributable is False
    assert a.safe_to_donate is False


def test_forecast_days_after_expiry_are_not_counted():
    """Demand beyond expiry cannot clear this batch."""
    pts = [
        {"target_date": NOW.date(), "p10": 0.0, "p50": 10.0, "p90": 20.0},
        {"target_date": (NOW + _dt.timedelta(days=10)).date(), "p10": 0.0, "p50": 9999.0, "p90": 9999.0},
    ]
    a = R.assess(_input(expires_at=NOW + _dt.timedelta(hours=10), forecast=pts), safety=_safety(), now=NOW)
    assert a.expected_demand["p50"] == pytest.approx(10.0)
    assert a.horizon_days == 1


def test_expected_demand_excludes_past_days():
    pts = [
        {"target_date": (NOW - _dt.timedelta(days=2)).date(), "p10": 0.0, "p50": 5000.0, "p90": 5000.0},
        {"target_date": NOW.date(), "p10": 0.0, "p50": 10.0, "p90": 20.0},
    ]
    a = R.assess(_input(forecast=pts), safety=_safety(), now=NOW)
    assert a.expected_demand["p50"] == pytest.approx(10.0)


def test_priority_is_risk_times_value_at_risk():
    a = R.assess(_input(qty=240.0, unit_cost=18.0, forecast=_fc(50.0)), safety=_safety(), now=NOW)
    assert a.priority == pytest.approx(a.risk * a.value_at_risk)


def test_value_at_risk_uses_expected_unsold_not_full_stock():
    a = R.assess(_input(qty=100.0, unit_cost=10.0, forecast=_fc(60.0, spread=10.0)), safety=_safety(), now=NOW)
    assert a.value_at_risk == pytest.approx(a.expected_unsold * 10.0)


# --------------------------------------------------------------- residual --
def test_residual_rescores_on_less_stock():
    full = R.assess(_input(qty=240.0, forecast=_fc(60.0, spread=15.0)), safety=_safety(), now=NOW)
    res = R.assess_residual(full, 10.0, now=NOW)
    assert res.stock_qty == 10.0
    assert res.expected_unsold == 0.0
    assert res.risk < full.risk


def test_residual_keeps_the_same_demand_distribution():
    full = R.assess(_input(qty=240.0, forecast=_fc(60.0, spread=15.0)), safety=_safety(), now=NOW)
    res = R.assess_residual(full, 100.0, now=NOW)
    assert res.expected_demand == full.expected_demand
    assert res.donate_by == full.donate_by
    assert res.urgency_hours == full.urgency_hours


def test_residual_never_exceeds_original_stock():
    full = R.assess(_input(qty=50.0, forecast=_fc(10.0)), safety=_safety(), now=NOW)
    assert R.assess_residual(full, 999.0, now=NOW).stock_qty == 50.0


# ----------------------------------------------------------------- rank ---
def test_rank_orders_by_priority_then_urgency():
    safety = _safety()
    a = _mk("a", risk=0.9, urgency=5.0, value=100.0)
    b = _mk("b", risk=0.5, urgency=1.0, value=100.0)
    ordered = R.rank([a, b])
    assert [x.batch_id for x in ordered] == ["a", "b"]


def test_rank_ties_break_toward_the_more_urgent():
    low_urgency = _mk("z", risk=0.8, urgency=40.0, value=100.0)
    high_urgency = _mk("y", risk=0.8, urgency=1.0, value=100.0)
    assert [x.batch_id for x in R.rank([low_urgency, high_urgency])] == ["y", "z"]


def test_top_risk_filters_by_min_risk():
    items = [_mk("a", risk=0.9, urgency=1.0, value=10.0), _mk("b", risk=0.2, urgency=1.0, value=10.0)]
    assert [x.batch_id for x in R.top_risk(items, min_risk=0.5)] == ["a"]


def _mk(batch_id, *, risk, urgency, value):
    return R.RiskAssessment(
        batch_id=batch_id,
        item_id="i",
        location_id="l",
        item_name="n",
        food_class="cooked",
        computed_at=NOW,
        stock_qty=10.0,
        expected_demand={"p10": 0.0, "p50": 0.0, "p90": 0.0},
        expected_unsold=0.0,
        risk=risk,
        urgency_hours=urgency,
        donate_by=NOW,
        priority=risk * value,
        value_at_risk=value,
        status="high",
        safe_to_donate=True,
        redistributable=True,
        horizon_days=1,
        insufficient_history=False,
        model_version="v1",
        demand_sigma=1.0,
    )