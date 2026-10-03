"""Unit tests: impact arithmetic, action semantics and false-alarm tracking."""

from __future__ import annotations

import pytest

from app.projects.foodlink_predict import impact as I
from app.projects.foodlink_predict.config import ImpactConfig


def _cfg(**over):
    base = dict(co2e_kg_per_kg=2.5, kg_per_meal=0.35)
    base.update(over)
    return ImpactConfig(**base)


# ------------------------------------------------------------- compute ---
def test_donation_counts_kg_meals_money_and_co2e():
    r = I.compute(action_type="donate", qty=100.0, unit_weight_kg=0.35, unit_cost=18.0, config=_cfg())
    assert r.kg_saved == pytest.approx(35.0)
    assert r.meals == pytest.approx(100.0)  # 35 / 0.35
    assert r.money_saved == pytest.approx(1800.0)
    assert r.co2e_kg == pytest.approx(87.5)  # 35 * 2.5


def test_emission_factor_is_configurable():
    hi = I.compute(action_type="donate", qty=100.0, unit_weight_kg=1.0, unit_cost=0.0, config=_cfg(co2e_kg_per_kg=4.0))
    lo = I.compute(action_type="donate", qty=100.0, unit_weight_kg=1.0, unit_cost=0.0, config=_cfg(co2e_kg_per_kg=1.0))
    assert hi.co2e_kg == 4.0 * hi.kg_saved
    assert lo.co2e_kg == 1.0 * lo.kg_saved


def test_kg_per_meal_is_configurable():
    r = I.compute(action_type="donate", qty=100.0, unit_weight_kg=1.0, unit_cost=0.0, config=_cfg(kg_per_meal=0.5))
    assert r.meals == pytest.approx(200.0)


def test_compost_does_not_claim_meals_or_money():
    r = I.compute(action_type="compost", qty=100.0, unit_weight_kg=0.35, unit_cost=18.0, config=_cfg())
    assert r.meals == 0.0
    assert r.money_saved == 0.0
    assert r.co2e_kg == 0.0
    assert r.kg_saved == 0.0  # not diverted from landfill
    assert r.semantics["label"] == "waste stream - handled, not rescued"


def test_transfer_and_promotion_count_as_rescued():
    for action in ("transfer", "promotion", "buy_prepare_less"):
        r = I.compute(action_type=action, qty=100.0, unit_weight_kg=0.35, unit_cost=18.0, config=_cfg())
        assert r.kg_saved > 0
        assert r.meals > 0


def test_unknown_action_type_is_not_credited():
    r = I.compute(action_type="incinerate", qty=100.0, unit_weight_kg=0.35, unit_cost=18.0, config=_cfg())
    assert r.kg_saved == 0.0
    assert "unknown action type" in r.semantics["label"]


def test_negative_quantity_is_clamped_to_zero():
    r = I.compute(action_type="donate", qty=-50.0, unit_weight_kg=0.35, unit_cost=18.0, config=_cfg())
    assert r.kg_saved == 0.0
    assert r.meals == 0.0


def test_invalid_factors_are_rejected():
    with pytest.raises(ValueError):
        _cfg(co2e_kg_per_kg=-1.0).validate()
    with pytest.raises(ValueError):
        _cfg(kg_per_meal=0.0).validate()


# ----------------------------------------------------------- aggregate ---
class _Ev:
    def __init__(self, action_type, location_id, day, kg, meals, money, co2e):
        self.action_type = action_type
        self.location_id = location_id
        self.recorded_at = day
        self.kg_saved = kg
        self.meals = meals
        self.money_saved = money
        self.co2e_kg = co2e


def _events():
    import datetime as _dt

    d1 = _dt.datetime(2026, 10, 1, tzinfo=_dt.timezone.utc)
    d2 = _dt.datetime(2026, 10, 2, tzinfo=_dt.timezone.utc)
    return [
        _Ev("donate", "l1", d1, 10.0, 20.0, 100.0, 25.0),
        _Ev("donate", "l2", d1, 5.0, 10.0, 50.0, 12.5),
        _Ev("compost", "l1", d2, 0.0, 0.0, 0.0, 0.0),
    ]


def test_aggregate_totals_by_action_location_and_day():
    out = I.aggregate(_events())
    assert out["event_count"] == 3
    assert out["totals"]["kg_saved"] == pytest.approx(15.0)
    assert out["totals"]["meals"] == pytest.approx(30.0)
    assert out["by_action"]["donate"]["kg_saved"] == pytest.approx(15.0)
    assert out["by_action"]["compost"]["meals"] == 0.0
    assert out["by_location"]["l1"]["kg_saved"] == pytest.approx(10.0)
    assert "2026-10-01" in out["by_day"]


def test_aggregate_states_the_factors_it_used():
    out = I.aggregate(_events(), config=_cfg(co2e_kg_per_kg=3.0))
    assert out["factors"]["emission_factor_co2e_per_kg"] == 3.0
    assert "indicative" in out["factors"]["note"]


def test_aggregate_handles_an_empty_ledger():
    out = I.aggregate([])
    assert out["event_count"] == 0
    assert out["totals"]["kg_saved"] == 0.0


def test_aggregate_assigns_events_without_a_location():
    import datetime as _dt

    ev = _Ev("donate", None, _dt.datetime(2026, 10, 1, tzinfo=_dt.timezone.utc), 1.0, 1.0, 1.0, 1.0)
    out = I.aggregate([ev])
    assert "unassigned" in out["by_location"]