"""Shared fixtures for the FoodLink Predict suite.

Scoped to this directory on purpose. The starter's own tests build their app at
import time with a module-level TestClient; a repo-root conftest.py with autouse
fixtures would change their behaviour. Keeping FLP fixtures under tests/flp/
means these tests get isolation and the starter's tests are untouched.

Performance note: seeding writes ~560 sales rows and fitting the forecaster costs
a few seconds. Doing that per test dominated the suite runtime and none of it is
per-test state, so the database is session-scoped and the corpus + forecasts are
seeded once per module. Isolation comes from three cheaper places instead:

  * every test that needs private data uses a UNIQUE org_id (org-scoped rows);
  * ``seeded_forecast`` deletes all mutable rows for the module org per test;
  * config caches and adapters are reset per test so env changes take effect.

Every test that writes (recommendations, listings, impact) goes through
``seeded_forecast``, so the cleanup covers all of them.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import uuid
from pathlib import Path

import pytest

# tests/flp/conftest.py -> backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("APP_MODE", "DEMO")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("FOODLINK_ADAPTER_MODE", "demo")

# The organization used by the shared, module-seeded corpus.
MODULE_ORG = "org_flp_module"

# A fixed clock, for tests that pin one. The seeded corpus is anchored to the
# REAL clock so its donate-by windows are live; tests that need determinism pass
# as_of explicitly instead.
PINNED_AS_OF = _dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=_dt.timezone.utc)


@pytest.fixture(scope="session")
def _flp_db(tmp_path_factory):
    """One SQLite file for the whole FLP suite."""
    from app.core.config import get_settings

    from app.projects.foodlink_predict import config as FLPConfig
    from app.projects.foodlink_predict import db as DB

    db_file = tmp_path_factory.mktemp("flp") / "flp.db"
    url = f"sqlite:///{db_file.as_posix()}"
    os.environ["FOODLINK_PREDICT_DB_URL"] = url
    get_settings.cache_clear()
    FLPConfig.reset_all_caches()
    DB.reset_engine()
    yield url
    DB.reset_engine()


@pytest.fixture(autouse=True)
def _flp_isolation(monkeypatch, _flp_db):
    """Per-test config reset + a clean slate for anything a test can write."""
    from app.core.config import get_settings

    from app.projects.foodlink_predict import config as FLPConfig
    from app.projects.foodlink_predict.adapters import reset_adapters

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("FOODLINK_ADAPTER_MODE", "demo")
    monkeypatch.setenv("FOODLINK_API_URL", "")
    monkeypatch.setenv("FOODLINK_LISTING_PATH", "")
    monkeypatch.setenv("SAFE_WINDOWS_JSON", "")

    get_settings.cache_clear()
    FLPConfig.reset_all_caches()
    reset_adapters()

    # Clear mutable state left by a previous test in this module. Cheap (a few
    # DELETE statements) compared with re-seeding and re-fitting.
    _clear_mutable(MODULE_ORG)

    yield

    get_settings.cache_clear()
    FLPConfig.reset_all_caches()
    reset_adapters()
    _clear_mutable(MODULE_ORG)


def _clear_mutable(org_id: str) -> None:
    from app.projects.foodlink_predict.db import delete_where, session_scope
    from app.projects.foodlink_predict.models import (
        ImpactEvent,
        Recommendation,
        RunRecord,
        SurplusListing,
        WasteRisk,
    )

    try:
        with session_scope() as sess:
            for model in (ImpactEvent, SurplusListing, Recommendation, WasteRisk, RunRecord):
                delete_where(sess, model, org_id)
    except Exception:
        # Before the first seed there is nothing to clear.
        pass


@pytest.fixture()
def org_id() -> str:
    """A private organization per test. Rows are org-scoped, so this isolates."""
    from app.projects.foodlink_predict.tenancy import ensure_org_exists

    oid = f"org_test_{uuid.uuid4().hex[:8]}"
    ensure_org_exists(oid, "Test Org")
    return oid


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="module")
def seeded_forecast(_flp_db):
    """Corpus + forecasts, seeded ONCE per module and shared read-only."""
    from app.projects.foodlink_predict import service as S
    from app.projects.foodlink_predict import synthetic
    from app.projects.foodlink_predict.db import session_scope
    from app.projects.foodlink_predict.tenancy import ensure_org_exists
    from app.projects.foodlink_predict.util import utcnow

    ensure_org_exists(MODULE_ORG, "Module Fixture Org")
    ds = synthetic.generate(as_of=utcnow())
    with session_scope() as sess:
        synthetic.load_into_db(sess, MODULE_ORG, ds)
    S.run_forecast(MODULE_ORG, horizon_days=7, include_backtest=False)
    return MODULE_ORG


@pytest.fixture()
def seeded(org_id):
    """A freshly seeded PRIVATE org, anchored to the real clock."""
    from app.projects.foodlink_predict import synthetic
    from app.projects.foodlink_predict.db import session_scope
    from app.projects.foodlink_predict.util import utcnow

    ds = synthetic.generate(as_of=utcnow())
    with session_scope() as sess:
        synthetic.load_into_db(sess, org_id, ds)
    return org_id


def make_forecast_rows(
    item_id: str,
    location_id: str,
    *,
    p50: float,
    spread: float = 20.0,
    days: int = 3,
    start: _dt.date | None = None,
) -> list[dict]:
    """Hand-built forecast rows, so risk can be tested without the model."""
    start = start or PINNED_AS_OF.date()
    return [
        {
            "target_date": start + _dt.timedelta(days=i),
            "p10": max(0.0, p50 - spread),
            "p50": p50,
            "p90": p50 + spread,
            "model_version": "test_v1",
            "method": "model",
        }
        for i in range(days)
    ]


__all__ = ["MODULE_ORG", "PINNED_AS_OF", "make_forecast_rows"]