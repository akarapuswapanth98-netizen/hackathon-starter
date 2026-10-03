"""Degraded-mode tests: the app must work with the optional ML group absent.

scikit-learn lives in `requirements-foodlink-predict.txt`, not the core
`requirements.txt`. A fresh clone that skips it must still boot, still forecast,
and still refuse donations honestly - with every cold-start row labelled.

These tests simulate the absence by blocking the imports, so they run whether or
not scikit-learn is installed on the machine.
"""

from __future__ import annotations

import importlib
import importlib.abc
import sys

import pytest


class _BlockML(importlib.abc.MetaPathFinder):
    """Make sklearn/pandas/numpy unimportable, as if the optional group is absent."""

    BLOCKED = {"sklearn", "pandas", "numpy", "joblib", "shap", "xgboost"}

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.BLOCKED:
            raise ImportError(f"optional ML dependency blocked for this test: {name}")
        return None


@pytest.fixture()
def no_ml(monkeypatch):
    """Purge the ML modules from sys.modules and block re-import."""
    saved = {k: v for k, v in sys.modules.items() if k.split(".")[0] in _BlockML.BLOCKED}
    for key in saved:
        monkeypatch.delitem(sys.modules, key, raising=False)
    blocker = _BlockML()
    monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
    yield
    # pytest restores sys.modules/sys.meta_path via monkeypatch.


def test_app_boots_without_the_optional_ml_group(no_ml):
    from app.main import create_app

    app = create_app()
    assert app is not None
    # app.routes holds _IncludedRouter objects in this FastAPI version, so the
    # OpenAPI schema is the reliable way to enumerate the mounted surface.
    paths = app.openapi()["paths"]
    assert "/api/forecast" in paths
    assert "/api/risk" in paths
    assert "/api/recommend" in paths
    assert "/api/surplus" in paths
    assert "/api/impact" in paths


def test_forecast_module_imports_without_sklearn(no_ml):
    from app.projects.foodlink_predict import forecast as F

    assert F.sklearn_available() is False


def test_forecast_falls_back_to_cold_start_and_says_so(no_ml, seeded):
    from app.projects.foodlink_predict import service as S

    result = S.run_forecast(seeded, horizon_days=5, include_backtest=False)
    assert result["model"] == "none"
    assert "scikit-learn" in result["model_error"]
    assert len(result["cold_start_series"]) > 0
    assert result["rows_written"] > 0  # still produced real rows


def test_every_cold_start_row_is_labelled(no_ml, seeded):
    from app.projects.foodlink_predict import service as S

    S.run_forecast(seeded, horizon_days=5, include_backtest=False)
    rows = S.stored_forecast(seeded)
    assert rows
    assert all(r["method"] == "cold_start" for r in rows)
    assert all(r["model_version"] != "unknown" for r in rows)


def test_cold_start_quantiles_are_ordered(no_ml, seeded):
    from app.projects.foodlink_predict import service as S

    S.run_forecast(seeded, horizon_days=5, include_backtest=False)
    for row in S.stored_forecast(seeded):
        assert 0 <= row["p10"] <= row["p50"] <= row["p90"]


def test_full_demo_completes_without_ml(no_ml):
    """The whole workflow still runs; donations are refused, and visibly so."""
    import asyncio

    from app.projects.foodlink_predict.demo import scenario

    out = asyncio.run(scenario.run_async("org_noml_demo", as_of="2026-10-03T06:00:00Z"))
    assert out["completed"] is True
    names = [s["name"] for s in out["steps"]]
    assert any("demand forecast" in n for n in names)
    assert any("recommendation agent" in n for n in names)
    assert any("impact ledger" in n for n in names)

    forecast_step = next(s for s in out["steps"] if s["name"] == "demand forecast")
    assert forecast_step["detail"]["ml_available"] is False
    assert forecast_step["detail"]["model_error"]

    # With no modelled forecast, the validator must refuse donations rather than
    # let a cold-start number authorise food reaching a person.
    listing_step = next(s for s in out["steps"] if "FORECAST listing" in s["name"])
    assert listing_step["status"] in ("skipped", "refused")


def test_backtest_is_honest_without_sklearn(no_ml, seeded):
    from app.projects.foodlink_predict import forecast as F
    from app.projects.foodlink_predict import service as S
    from app.projects.foodlink_predict.db import session_scope
    from app.projects.foodlink_predict.models import CalendarDay

    with session_scope() as sess:
        series = F.load_series(sess, seeded)
        calendar = F.calendar_index(
            sess.query(CalendarDay).filter(CalendarDay.org_id == seeded).all()
        )
    out = F.backtest(series, calendar, test_days=7, cold_start_days=14, refit_every_days=7)
    if out.get("available"):
        # Every point fell back to the baseline; the count must say so rather
        # than presenting a model WAPE that was never produced.
        assert out["baseline_fallback_points"] == out["n_points"]
        assert out["caveat"]
    else:
        assert out["reason"]


def test_unknown_forecast_model_fails_fast_with_a_clear_message(monkeypatch):
    """A typo in FORECAST_MODEL must not surface as an obscure mid-fit crash."""
    from app.core.config import get_settings

    from app.projects.foodlink_predict import config as FLPConfig
    from app.projects.foodlink_predict.errors import CapabilityUnavailable
    from app.projects.foodlink_predict.forecast import QuantileForecaster

    monkeypatch.setenv("FORECAST_MODEL", "telepathy")
    get_settings.cache_clear()
    FLPConfig.reset_all_caches()
    try:
        with pytest.raises(CapabilityUnavailable) as exc:
            QuantileForecaster()
        assert "telepathy" in str(exc.value)
        assert "gradient_boosting" in str(exc.value.detail or "")
    finally:
        get_settings.cache_clear()
        FLPConfig.reset_all_caches()