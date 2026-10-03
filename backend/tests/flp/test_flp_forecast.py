"""Unit tests: forecasting, baseline, metrics, cold start, feature leakage."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.projects.foodlink_predict import forecast as F
from app.projects.foodlink_predict.features import (
    FEATURE_NAMES,
    Series,
    bias,
    build_series,
    cold_start_forecast,
    feature_row,
    seasonal_naive,
    smape,
    wape,
)


class _Row:
    def __init__(self, date, qty_sold, promo_flag=False):
        self.date = date
        self.qty_sold = qty_sold
        self.promo_flag = promo_flag


def _series(values: list[float], *, start: _dt.date | None = None, category="mains", item="i", loc="l"):
    start = start or _dt.date(2026, 1, 1)
    rows = [_Row(start + _dt.timedelta(days=i), v, i % 7 == 3) for i, v in enumerate(values)]
    return build_series(rows, item_id=item, location_id=loc, category=category)


# ---------------------------------------------------------------- metrics --
def test_wape_zero_for_perfect_forecast():
    assert wape([10, 20, 30], [10, 20, 30]) == 0.0


def test_wape_known_value():
    # sum|y-yhat| = 5+5+10 = 20 ; sum|y| = 60 -> 1/3
    assert wape([10, 20, 30], [15, 15, 40]) == pytest.approx(20 / 60)


def test_wape_all_zero_actual_is_not_an_error():
    assert wape([0, 0, 0], [5, 5, 5]) == 0.0


def test_wape_length_mismatch_raises():
    with pytest.raises(ValueError):
        wape([1, 2], [1])


def test_bias_sign_reports_over_forecasting():
    # over-forecast -> positive bias
    assert bias([10, 10], [12, 12]) == pytest.approx(0.2)
    # under-forecast -> negative bias
    assert bias([10, 10], [8, 8]) == pytest.approx(-0.2)


def test_bias_zero_actual_is_not_an_error():
    assert bias([0, 0], [5, 5]) == 0.0


def test_smape_is_scale_invariant():
    """sMAPE's defining property: doubling every value changes nothing.

    (It is *not* symmetric around the midpoint under the standard definition -
    that is a known quirk of sMAPE, not a bug here - so the invariant worth
    asserting is scale-invariance.)
    """
    a = smape([10.0, 20.0], [12.0, 18.0])
    b = smape([100.0, 200.0], [120.0, 180.0])
    assert a == pytest.approx(b)


# --------------------------------------------------------------- baseline --
def test_seasonal_naive_uses_same_weekday_last_week():
    s = _series([100.0] * 21)
    target = s.dates[20]  # a Wednesday
    assert seasonal_naive(s, target) == 100.0
    # ...and specifically the value exactly 7 days earlier.
    assert seasonal_naive(s, target) == s.qty[13]


def test_seasonal_naive_returns_zero_without_history():
    s = _series([50.0, 60.0])
    assert seasonal_naive(s, s.dates[-1]) == 0.0  # no data 7 days back


def test_seasonal_naive_ignores_non_seven_day_lag():
    s = _series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 999.0])  # index 7 is +1 day
    assert seasonal_naive(s, s.dates[7]) == 1.0  # index 0, not 999


# --------------------------------------------------------------- features --
def test_feature_vector_width_matches_declared_names():
    s = _series([10.0] * 30)
    vector, meta = feature_row(s, s.dates[-1] + _dt.timedelta(days=1))
    assert len(vector) == len(FEATURE_NAMES)
    assert meta["history_points"] == len(s)


def test_features_do_not_leak_the_target_day():
    """The target day's own value must not influence its own features."""
    s = _series([10.0] * 30)
    target = s.dates[20]
    s.qty[20] = 999_999.0
    vector, _ = feature_row(s, target + _dt.timedelta(days=1))
    # index 7 is lag_7 -> reads index 13, not the mutated index 20
    assert vector[7] == 10.0
    assert 999_999.0 not in vector


def test_lag_7_and_lag_14_read_the_right_offsets():
    values = [float(i) for i in range(40)]
    s = _series(values)
    target = s.dates[-1] + _dt.timedelta(days=1)  # conceptually index 40
    vector, _ = feature_row(s, target)
    assert vector[7] == 33.0  # target-7 == index 33
    assert vector[8] == 26.0  # target-14 == index 26


def test_rolling_mean_7_averages_the_prior_week_only():
    values = [10.0] * 7 + [100.0] * 7
    s = _series(values)
    target = s.dates[-1] + _dt.timedelta(days=1)
    vector, _ = feature_row(s, target)
    assert vector[9] == pytest.approx(100.0)  # the recent week dominates


def test_rolling_mean_7_excludes_the_target_day_itself():
    """Even when the target date already has an observed value, it is excluded."""
    values = [10.0] * 7 + [100.0] * 7
    s = _series(values)
    target = s.dates[10]  # an already-observed date
    before, _ = feature_row(s, target)
    s.qty[10] = 999_999.0  # mutate the target day
    after, _ = feature_row(s, target)
    assert after[9] == pytest.approx(before[9])  # roll_mean_7 unchanged


def test_holiday_flag_and_distance_flow_into_features():
    s = _series([10.0] * 30)
    target = s.dates[-1] + _dt.timedelta(days=1)
    _, meta = feature_row(s, target, is_holiday=True, days_to_holiday=3)
    assert meta["is_holiday"] is True
    assert meta["days_to_holiday"] == 3.0


def test_days_to_holiday_is_capped():
    s = _series([10.0] * 30)
    target = s.dates[-1] + _dt.timedelta(days=1)
    vector, _ = feature_row(s, target, days_to_holiday=5000)
    assert vector[6] == 999.0


# ------------------------------------------------------------- cold start --
def test_cold_start_is_used_below_the_threshold():
    short = _series([10.0] * 5)  # well under 14 days
    res = F.forecast_series(short, 3, {}, model=None, cold_start_days=14, as_of=_dt.date(2026, 1, 6))
    assert res.method == "cold_start"
    assert all(p.method == "cold_start" for p in res.points)
    assert res.model_version != "unknown"


def test_cold_start_below_threshold_never_calls_the_model():
    """A 10-day series must not be modelled even when a model is supplied."""
    short = _series([10.0] * 10)

    class Exploding:
        kind = "gradient_boosting"
        params: dict = {}

        def predict_point(self, *a, **k):  # pragma: no cover - must never run
            raise AssertionError("model was called for a cold-start series")

        def calibration_summary(self):  # pragma: no cover
            return {}

    res = F.forecast_series(
        short, 3, {}, model=Exploding(), cold_start_days=14, as_of=_dt.date(2026, 1, 11)
    )
    assert res.method == "cold_start"


def test_cold_start_quantiles_are_ordered_and_non_negative():
    p10, p50, p90 = cold_start_forecast(
        _dt.date(2026, 1, 5), category_mean=100.0, location_mean=90.0, global_mean=80.0
    )
    assert 0 <= p10 <= p50 <= p90


def test_cold_start_without_any_prior_returns_zero():
    p10, p50, p90 = cold_start_forecast(_dt.date(2026, 1, 5))
    assert (p10, p50, p90) == (0.0, 0.0, 0.0)


def test_cold_start_suppresses_weekends():
    _, weekday, _ = cold_start_forecast(_dt.date(2026, 1, 5), category_mean=100.0, location_mean=100.0, global_mean=100.0)
    _, weekend, _ = cold_start_forecast(_dt.date(2026, 1, 10), category_mean=100.0, location_mean=100.0, global_mean=100.0)
    assert weekend < weekday


# -------------------------------------------------- quantile hygiene -------
def test_enforce_quantile_order_repairs_crossed_quantiles():
    assert F.enforce_quantile_order(50.0, 10.0, 5.0) == (10.0, 10.0, 10.0)
    assert F.enforce_quantile_order(5.0, 50.0, 1.0) == (5.0, 5.0, 5.0)


def test_enforce_quantile_order_keeps_good_input():
    assert F.enforce_quantile_order(10.0, 20.0, 30.0) == (10.0, 20.0, 30.0)


def test_enforce_quantile_order_never_returns_negative():
    out = F.enforce_quantile_order(-5.0, -1.0, 10.0)
    assert all(v >= 0 for v in out)


# ------------------------------------------------------------ backtest -----
def test_backtest_refuses_when_history_is_too_short():
    short = [_series([10.0] * 5) for _ in range(3)]
    out = F.backtest(short, {}, test_days=14, cold_start_days=14)
    assert out["available"] is False
    assert "reason" in out
    # Critically: it must not fabricate a flattering 0.0 WAPE.
    assert out["model"] == {}


def test_backtest_reports_both_model_and_baseline(seeded_forecast):
    from app.projects.foodlink_predict import service as S
    from app.projects.foodlink_predict.db import session_scope
    from app.projects.foodlink_predict.models import CalendarDay

    with session_scope() as sess:
        series = F.load_series(sess, seeded_forecast)
        calendar = F.calendar_index(sess.query(CalendarDay).filter(CalendarDay.org_id == seeded_forecast).all())
    out = F.backtest(series, calendar, test_days=14, cold_start_days=14, refit_every_days=7)
    assert out["available"] is True
    assert out["n_points"] > 0
    for block in ("model", "baseline"):
        assert "wape" in out[block]
        assert "bias" in out[block]
        assert 0.0 <= out[block]["wape"] <= 10.0
    assert out["baseline"]["name"] == "seasonal_naive_lag7"
    assert "improvement_vs_baseline" in out


def test_calendar_index_derives_days_to_next_holiday():
    from app.projects.foodlink_predict.models import CalendarDay

    rows = [
        CalendarDay(org_id="o", date=_dt.date(2026, 10, 1), is_holiday=False, day_of_week=3),
        CalendarDay(org_id="o", date=_dt.date(2026, 10, 5), is_holiday=True, holiday_name="H", day_of_week=0),
    ]
    idx = F.calendar_index(rows)
    assert idx[_dt.date(2026, 10, 1)]["days_to_holiday"] == 4.0
    assert idx[_dt.date(2026, 10, 5)]["days_to_holiday"] == 0.0
    assert idx[_dt.date(2026, 10, 5)]["is_holiday"] is True


def test_weather_score_is_none_when_absent_and_known_when_present():
    assert F._weather_score(None) is None
    assert F._weather_score("") is None
    assert F._weather_score("Clear") == 1.0
    assert F._weather_score("heavy rain") == 0.1


# ------------------------------------------------- model fitting (sklearn) --
@pytest.mark.skipif(not F.sklearn_available(), reason="scikit-learn not installed")
def test_quantile_forecaster_fits_and_calibrates():
    import random

    rng = random.Random(7)
    values = [100 + 40 * ((i % 7) in (4,)) + rng.gauss(0, 5) for i in range(70)]
    s = _series(values)
    model = F.QuantileForecaster().fit([s], {})
    assert model.calibration_points > 0
    assert model.offset_lo <= 0 <= model.offset_hi or model.offset_hi > 0
    p10, p50, p90 = model.predict_point(s, s.dates[-1] + _dt.timedelta(days=1), {})
    assert 0 <= p10 <= p50 <= p90


@pytest.mark.skipif(not F.sklearn_available(), reason="scikit-learn not installed")
def test_unknown_forecast_model_raises_capability_error():
    from app.projects.foodlink_predict.errors import CapabilityUnavailable

    with pytest.raises(CapabilityUnavailable):
        F.QuantileForecaster(kind="telepathy")