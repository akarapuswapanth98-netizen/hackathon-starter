"""Unit tests: the FoodLink adapter boundary.

The rule these tests protect: FoodLink Predict must never guess FoodLink's
schema, and the demo adapter must never be mistakable for a real hand-off.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from app.projects.foodlink_predict.adapters import (
    FoodLinkUnavailable,
    ListingRejected,
    canonical_listing,
    describe,
    get_adapter,
)
from app.projects.foodlink_predict.adapters.base import FoodLinkAdapter, FoodLinkError
from app.projects.foodlink_predict.adapters.demo import DemoFoodLinkAdapter
from app.projects.foodlink_predict.adapters.http import HttpFoodLinkAdapter

NOW = _dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=_dt.timezone.utc)


def _listing(**over):
    p = dict(
        listing_id="lst_1",
        org_id="o1",
        location={"id": "l1", "name": "Canteen", "lat": 17.385, "lng": 78.4867, "timezone": "UTC"},
        items=[
            {
                "item_id": "i1",
                "name": "Cooked Rice",
                "category": "mains",
                "food_class": "cooked",
                "qty": 100.0,
                "qty_kg": 35.0,
                "unit": "portion",
            }
        ],
        ready_at=NOW,
        donate_by=NOW + _dt.timedelta(hours=10),
        storage="hot",
        confidence=0.87,
        status="forecast",
    )
    p.update(over)
    return p


# ------------------------------------------------------------- canonical --
def test_canonical_listing_matches_the_proposed_contract():
    doc = canonical_listing(**_listing())
    for key in ("listing_id", "org_id", "location", "items", "ready_at", "donate_by", "storage", "confidence", "status", "source"):
        assert key in doc, f"missing contract field {key}"
    assert doc["source"] == "waste-predictor"
    assert doc["status"] == "forecast"


def test_canonical_listing_flags_cooked_items():
    doc = canonical_listing(**_listing())
    assert doc["items"][0]["cooked"] is True


def test_canonical_listing_rejects_an_unknown_status():
    with pytest.raises(FoodLinkError):
        canonical_listing(**_listing(status="maybe"))


# ----------------------------------------------------------------- demo ---
def test_demo_adapter_satisfies_the_interface():
    assert isinstance(DemoFoodLinkAdapter(), FoodLinkAdapter)


def test_create_forecast_listing_marks_the_response_as_simulated():
    adapter = DemoFoodLinkAdapter()
    res = adapter.create_forecast_listing(_listing())
    assert res["status"] == "forecast"
    assert res["demo"] is True
    assert res["simulated"] is True
    assert res["real_foodlink_executed"] is False
    assert res["executed_by"] == "demo-simulator"


def test_demo_adapter_states_what_real_foodlink_would_do():
    res = DemoFoodLinkAdapter().create_forecast_listing(_listing())
    assert "Detect" in res["expected_foodlink_behaviour"]


def test_confirm_pins_confidence_to_one():
    adapter = DemoFoodLinkAdapter()
    adapter.create_forecast_listing(_listing())
    res = adapter.confirm_listing("lst_1", confirmed_qty=90.0, confirmed_by="staff")
    assert res["status"] == "confirmed"
    assert res["confidence"] == 1.0


def test_confirm_rejects_a_non_positive_quantity():
    adapter = DemoFoodLinkAdapter()
    adapter.create_forecast_listing(_listing())
    with pytest.raises(ListingRejected):
        adapter.confirm_listing("lst_1", confirmed_qty=0.0)


def test_withdraw_clears_confidence_and_records_a_reason():
    adapter = DemoFoodLinkAdapter()
    adapter.create_forecast_listing(_listing())
    res = adapter.withdraw_listing("lst_1", reason="sales_caught_up")
    assert res["status"] == "withdrawn"
    assert res["confidence"] == 0.0


def test_state_machine_forbids_confirming_a_withdrawn_listing():
    adapter = DemoFoodLinkAdapter()
    adapter.create_forecast_listing(_listing())
    adapter.withdraw_listing("lst_1")
    with pytest.raises(ListingRejected):
        adapter.confirm_listing("lst_1")


def test_cannot_withdraw_twice():
    adapter = DemoFoodLinkAdapter()
    adapter.create_forecast_listing(_listing())
    adapter.withdraw_listing("lst_1")
    with pytest.raises(ListingRejected):
        adapter.withdraw_listing("lst_1")


def test_duplicate_publish_is_idempotent_when_identical():
    adapter = DemoFoodLinkAdapter()
    first = adapter.create_forecast_listing(_listing())
    second = adapter.create_forecast_listing(_listing())
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert adapter.listing_count() == 1


def test_duplicate_id_with_different_content_is_a_conflict():
    adapter = DemoFoodLinkAdapter()
    adapter.create_forecast_listing(_listing())
    with pytest.raises(ListingRejected):
        adapter.create_forecast_listing(_listing(confidence=0.1))


def test_unknown_listing_raises_not_found():
    with pytest.raises(FoodLinkUnavailable):
        DemoFoodLinkAdapter().get_listing_status("nope")


def test_empty_listing_is_rejected():
    with pytest.raises(ListingRejected):
        DemoFoodLinkAdapter().create_forecast_listing(_listing(items=[]))


def test_missing_listing_id_is_rejected():
    with pytest.raises(ListingRejected):
        DemoFoodLinkAdapter().create_forecast_listing(_listing(listing_id=""))


def test_foodlink_unavailable_is_reported_not_swallowed():
    adapter = DemoFoodLinkAdapter()
    adapter.simulate_unavailable(True)
    with pytest.raises(FoodLinkUnavailable):
        adapter.create_forecast_listing(_listing())
    adapter.simulate_unavailable(False)
    assert adapter.create_forecast_listing(_listing())["status"] == "forecast"


# ----------------------------------------------------------------- http ---
def test_http_adapter_refuses_without_a_configured_contract():
    """The single most important test: no guessing FoodLink's schema."""
    adapter = HttpFoodLinkAdapter(base_url="", listing_path="")
    with pytest.raises(FoodLinkUnavailable) as exc:
        adapter.create_forecast_listing(_listing())
    assert "FOODLINK_API_URL" in str(exc.value)
    assert "FOODLINK_LISTING_PATH" in str(exc.value)


def test_http_adapter_refuses_when_only_the_url_is_set():
    adapter = HttpFoodLinkAdapter(base_url="https://foodlink.example", listing_path="")
    with pytest.raises(FoodLinkUnavailable):
        adapter.create_forecast_listing(_listing())


def test_http_adapter_marks_its_contract_as_unverified():
    """If a path IS configured, the response must say the mapping is unverified."""
    seen = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"id": "fl_1", "status": "received"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, json=None, headers=None):
            seen.update({"method": method, "url": url, "body": json})
            return _Resp()

    adapter = HttpFoodLinkAdapter(base_url="https://foodlink.example", listing_path="/api/listings")
    import httpx

    original = httpx.Client
    httpx.Client = _Client
    try:
        res = adapter.create_forecast_listing(_listing())
    finally:
        httpx.Client = original
    assert res["contract_verified"] is False
    assert "UNVERIFIED" in res["note"]
    assert seen["method"] == "POST"
    assert seen["url"] == "https://foodlink.example/api/listings"


def test_http_adapter_surfaces_a_rejection():
    class _Resp:
        status_code = 422

        def json(self):
            return {"error": "bad"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            return _Resp()

    adapter = HttpFoodLinkAdapter(base_url="https://x.example", listing_path="/l")
    import httpx

    original = httpx.Client
    httpx.Client = _Client
    try:
        with pytest.raises(ListingRejected):
            adapter.create_forecast_listing(_listing())
    finally:
        httpx.Client = original


# ------------------------------------------------------------- factory ---
def test_demo_is_the_default_mode():
    assert get_adapter().mode == "demo"


def test_disabled_mode_raises_capability_error():
    from app.projects.foodlink_predict.errors import CapabilityUnavailable

    with pytest.raises(CapabilityUnavailable):
        get_adapter("disabled")


def test_unknown_mode_is_rejected():
    from app.projects.foodlink_predict.errors import CapabilityUnavailable

    with pytest.raises(CapabilityUnavailable):
        get_adapter("telepathy")


def test_describe_reports_the_unverified_contract():
    info = describe()
    assert info["mode"] == "demo"
    assert info["contract_verified"] is False
    assert "UNVERIFIED" in info["contract_status"]


def test_describe_never_leaks_a_key():
    info = describe()
    blob = str(info).lower()
    for secret_word in ("sk-", "bearer", "api_key\":", "secret"):
        assert secret_word not in blob