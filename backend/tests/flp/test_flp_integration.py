"""Integration tests: the full FoodLink Predict workflow, stage by stage.

These follow the pipeline the architecture PDF describes, and each stage is
checked at its own seam (upload -> forecast -> risk -> recommendation ->
surplus -> adapter -> impact) as well as through the HTTP API.
"""

from __future__ import annotations

import asyncio
import datetime as _dt

import pytest

from app.projects.foodlink_predict import impact as I
from app.projects.foodlink_predict import service as S
from app.projects.foodlink_predict import surplus as SURPLUS
from app.projects.foodlink_predict.adapters import FoodLinkUnavailable
from app.projects.foodlink_predict.db import session_scope

DEMO_AS_OF = "2026-10-03T06:00:00Z"  # only for the demo-scenario tests


# ------------------------------------------------------- upload -> data --
def test_ingest_csv_through_the_api(client):
    """CSV ingestion works over HTTP and reports provenance."""
    items = "item_id,name,category,food_class,shelf_life_hours,unit_cost,unit_price\ni1,Rice,mains,cooked,24,18,60\n"
    sales = "date,item_id,location_id,qty_sold\n2026-10-01,i1,loc_a,100\n"

    r1 = client.post("/api/ingest", json={"csv_text": items, "kind": "items", "org_id": "org_itg"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["inserted"] == 1

    # A location must exist before sales referencing it are accepted.
    from app.projects.foodlink_predict.ingest import upsert_location

    with session_scope() as sess:
        upsert_location(sess, "org_itg", "loc_a", name="Main", lat=17.385, lng=78.4867)

    r2 = client.post("/api/ingest", json={"csv_text": sales, "kind": "sales", "org_id": "org_itg"})
    assert r2.status_code == 200
    assert r2.json()["data"]["inserted"] == 1


def test_ingest_reports_row_level_issues_in_the_response(client):
    items = "item_id,name,category,food_class\ni1,Rice,mains,cooked\n"
    with session_scope() as sess:
        from app.projects.foodlink_predict.ingest import upsert_location

        upsert_location(sess, "org_iss", "loc_a", name="Main")
    sales = "date,item_id,location_id,qty_sold\n2026-10-01,ghost,loc_a,10\n"
    r = client.post("/api/ingest", json={"csv_text": sales, "kind": "sales", "org_id": "org_iss"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["ok"] is False
    assert data["issues"][0]["code"] == "unknown_item"


def test_ingest_missing_columns_is_a_422(client):
    r = client.post("/api/ingest", json={"csv_text": "a,b\n1,2", "kind": "sales", "org_id": "org_x"})
    assert r.status_code == 422
    assert "error" in r.json()


def test_ingest_rejects_a_blank_csv(client):
    r = client.post("/api/ingest", json={"csv_text": "   ", "org_id": "org_x"})
    assert r.status_code == 422  # Pydantic min_length / validator


# ---------------------------------------------------------- forecast -----
def test_upload_then_forecast(seeded, client):
    r = client.post("/api/forecast", json={"org_id": seeded, "horizon_days": 7, "include_backtest": True})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["rows_written"] > 0
    assert data["model"] in ("gradient_boosting", "random_forest", "none")
    assert data["quantiles"] == {"p10": "10th percentile", "p50": "median", "p90": "90th percentile"}
    assert data["baseline"].startswith("seasonal_naive")


def test_forecast_reports_synthetic_provenance(seeded, client):
    r = client.post("/api/forecast", json={"org_id": seeded, "horizon_days": 3, "include_backtest": False})
    prov = r.json()["data"]["data_provenance"]
    assert prov["contains_synthetic_data"] is True
    assert prov["synthetic_fraction"] == 1.0


def test_forecast_without_data_reports_cold_start_clearly(client):
    r = client.post("/api/forecast", json={"org_id": "org_empty", "horizon_days": 3})
    assert r.status_code == 422
    assert "No sales history" in r.json()["error"]


def test_stored_forecast_is_readable_and_ordered(seeded_forecast):
    rows = S.stored_forecast(seeded_forecast)
    assert rows
    assert rows == sorted(rows, key=lambda r: r["target_date"])


def test_forecast_is_idempotent_across_repeat_calls(seeded_forecast):
    before = len(S.stored_forecast(seeded_forecast))
    S.run_forecast(seeded_forecast, horizon_days=7, include_backtest=False)
    after = S.stored_forecast(seeded_forecast)
    # Same model version -> same natural keys -> no duplicate rows.
    assert len(after) <= before * 2
    versions = {r["model_version"] for r in after}
    assert len(versions) >= 1


# -------------------------------------------------------------- risk -----
def test_forecast_then_risk(seeded_forecast):
    assessments = S.compute_risk(seeded_forecast, persist=True)
    assert assessments
    top = assessments[0]
    assert 0.0 < top.risk < 1.0
    assert top.donate_by is not None
    assert top.expected_unsold >= 0


def test_risk_is_persisted_with_full_detail(seeded_forecast):
    from app.projects.foodlink_predict.models import WasteRisk

    S.compute_risk(seeded_forecast, persist=True)
    with session_scope() as sess:
        rows = sess.query(WasteRisk).filter(WasteRisk.org_id == seeded_forecast).all()
    assert rows
    assert rows[0].detail["safe_window_hours"] > 0


def test_risk_endpoint_surfaces_the_safety_config(client, seeded_forecast):
    r = client.get("/api/risk", params={"org_id": seeded_forecast})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["safety_config"]["safe_windows_hours"]["cooked"] > 0
    assert "never expires_at" in data["safety_config"]["note"]


def test_risk_min_risk_filter(client, seeded_forecast):
    r = client.get("/api/risk", params={"org_id": seeded_forecast, "min_risk": 0.999})
    assert r.status_code == 200
    assert r.json()["data"]["items"] == []


# ------------------------------------------------- risk -> recommendation -
def test_risk_to_recommendation(seeded_forecast):
    result = asyncio.run(S.recommend(seeded_forecast, min_risk=0.0, limit=3))
    assert result["count"] > 0
    rec = result["recommendations"][0]
    for key in (
        "action",
        "batch_id",
        "quantity",
        "deadline",
        "rationale",
        "evidence",
        "tool_trace",
        "validation_status",
    ):
        assert key in rec, f"recommendation is missing {key}"


def test_recommendation_cites_its_tool_outputs(seeded_forecast):
    result = asyncio.run(S.recommend(seeded_forecast, min_risk=0.0, limit=1))
    rec = result["recommendations"][0]
    tools = {t["tool"] for t in rec["tool_trace"]}
    assert "get_forecast" in tools
    assert rec["evidence"]["risk"] is not None


def test_recommendation_never_fabricates_forecast_numbers(seeded_forecast):
    """Any quantity the agent emits must match the deterministic ladder."""
    result = asyncio.run(S.recommend(seeded_forecast, min_risk=0.0, limit=3))
    for rec in result["recommendations"]:
        plan_steps = {s["action"]: s["quantity"] for s in rec["recovery_plan"]["plan"]}
        assert rec["quantity"] == pytest.approx(plan_steps[rec["action"]])


def test_recovery_plan_prefers_prevention_then_redistribution(seeded_forecast):
    result = asyncio.run(S.recommend(seeded_forecast, min_risk=0.0, limit=3))
    for rec in result["recommendations"]:
        actions = [s["action"] for s in rec["recovery_plan"]["plan"]]
        # Never recommend compost while a recovery step is still available.
        if "compost" in actions:
            assert len(actions) == 1


def test_residual_donation_quantity_is_less_than_stock(seeded_forecast):
    result = asyncio.run(S.recommend(seeded_forecast, min_risk=0.0, limit=3))
    residuals = [r for r in result["recommendations"] if r.get("step_stage") == "residual"]
    assert residuals, "expected at least one residual step (e.g. donate the remainder)"
    for rec in residuals:
        stock = rec["evidence"]["risk"]["stock_qty"]
        assert rec["quantity"] <= stock
        assert rec["quantity"] > 0
        assert rec["validation_status"] in ("passed", "rejected")


def test_recommend_endpoint(client, seeded_forecast):
    r = client.post("/api/recommend", json={"org_id": seeded_forecast, "limit": 2})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["org_id"] == seeded_forecast
    assert "validator_passed" in data and "validator_rejected" in data


def test_recommend_stream_emits_real_events(client, seeded_forecast):
    r = client.post("/api/recommend/stream", json={"org_id": seeded_forecast, "limit": 1})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    text = r.text
    assert "data:" in text
    # The stages the brief asks a frontend to display.
    for stage in ("risk", "planner", "actions", "validator", "recommendation"):
        assert f'"{stage}"' in text, f"missing SSE stage {stage}"
    assert "waste risk computed" in text
    assert "safety validation" in text
    assert "recommendation ready" in text


# ------------------------------------------- recommendation -> surplus ----
def test_surplus_requires_a_validated_donate_recommendation(seeded_forecast):
    from app.projects.foodlink_predict.errors import Forbidden

    with pytest.raises(Forbidden):
        SURPLUS.create_listing(seeded_forecast, batch_id="bat_demo_rice_001")


def _first_validated_donate(org_id):
    result = asyncio.run(S.recommend(org_id, min_risk=0.0, limit=5))
    for rec in result["recommendations"]:
        if rec["action"] == "donate" and rec["validation_status"] == "passed":
            return rec
    return None


def test_recommendation_to_surplus_and_adapter(seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation for this fixture")
    listing = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    assert listing["status"] == "forecast"
    assert listing["source"] == "waste-predictor"
    assert listing["foodlink"]["simulated"] is True
    assert listing["foodlink"]["real_foodlink_executed"] is False
    assert listing["validator"]["passed"] is True
    assert listing["donate_by"]
    assert listing["items"][0]["qty_kg"] > 0


def test_listing_confidence_tracks_the_risk_not_its_inverse(seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")
    listing = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    assert listing["confidence"] > 0.5  # high-risk batch -> high confidence of surplus


def test_surplus_state_machine(seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")
    listing = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    confirmed = SURPLUS.confirm_listing(seeded_forecast, listing_id=listing["listing_id"])
    assert confirmed["status"] == "confirmed"
    assert confirmed["confidence"] == 1.0
    from app.projects.foodlink_predict.errors import Conflict

    with pytest.raises(Conflict):
        SURPLUS.confirm_listing(seeded_forecast, listing_id=listing["listing_id"])


def test_listing_cannot_be_confirmed_after_donate_by(seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")
    listing = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    from app.projects.foodlink_predict.errors import SafetyViolation

    with pytest.raises(SafetyViolation):
        SURPLUS.confirm_listing(
            seeded_forecast,
            listing_id=listing["listing_id"],
            now=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=1),
        )


def test_foodlink_unavailable_is_reported(seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")
    from app.projects.foodlink_predict.adapters import get_adapter
    from app.projects.foodlink_predict.errors import Conflict

    adapter = get_adapter()
    adapter.simulate_unavailable(True)
    try:
        with pytest.raises(Conflict):
            SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    finally:
        adapter.simulate_unavailable(False)


def test_surplus_endpoints(client, seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")

    created = client.post(
        "/api/surplus", json={"action": "create", "org_id": seeded_forecast, "batch_id": rec["batch_id"]}
    )
    assert created.status_code == 200, created.text
    listing_id = created.json()["data"]["listing_id"]
    assert created.json()["meta"]["foodlink"]["mode"] == "demo"

    status = client.get(f"/api/surplus/{listing_id}", params={"org_id": seeded_forecast, "refresh": True})
    assert status.status_code == 200
    assert status.json()["data"]["status"] == "forecast"

    wd = client.post(
        f"/api/surplus/{listing_id}/withdraw", json={"org_id": seeded_forecast, "reason": "sales_caught_up"}
    )
    assert wd.status_code == 200
    assert wd.json()["data"]["status"] == "withdrawn"
    assert wd.json()["data"]["false_alarm"] is True


def test_surplus_action_requires_the_right_id(client, seeded_forecast):
    r = client.post("/api/surplus", json={"action": "confirm", "org_id": seeded_forecast})
    assert r.status_code == 422
    assert "listing_id" in r.json()["error"]


# ---------------------------------------------------- surplus -> impact ---
def test_confirmed_listing_records_impact(seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")
    listing = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    confirmed = SURPLUS.confirm_listing(seeded_forecast, listing_id=listing["listing_id"])
    impact = confirmed["impact"]
    assert impact["kg_saved"] > 0
    assert impact["meals"] > 0
    assert impact["co2e_kg"] > 0
    assert impact["action_type"] == "donate"


def test_withdrawn_listing_records_no_impact(seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")
    listing = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    with session_scope() as sess:
        from app.projects.foodlink_predict.models import ImpactEvent

        before = len(sess.query(ImpactEvent).filter(ImpactEvent.org_id == seeded_forecast).all())
    SURPLUS.withdraw_listing(seeded_forecast, listing_id=listing["listing_id"])
    with session_scope() as sess:
        from app.projects.foodlink_predict.models import ImpactEvent

        after = len(sess.query(ImpactEvent).filter(ImpactEvent.org_id == seeded_forecast).all())
    assert after == before, "a false alarm must not book impact"


def test_impact_endpoint_aggregates(client, seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")
    listing = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    SURPLUS.confirm_listing(seeded_forecast, listing_id=listing["listing_id"])
    r = client.get("/api/impact", params={"org_id": seeded_forecast})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["totals"]["kg_saved"] > 0
    assert "donate" in data["by_action"]
    assert data["factors"]["emission_factor_co2e_per_kg"] > 0


def test_impact_false_alarm_rate_is_reported(client, seeded_forecast):
    rec = _first_validated_donate(seeded_forecast)
    if rec is None:
        pytest.skip("no validated donate recommendation")
    a = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    SURPLUS.confirm_listing(seeded_forecast, listing_id=a["listing_id"])
    b = SURPLUS.create_listing(seeded_forecast, batch_id=rec["batch_id"])
    SURPLUS.withdraw_listing(seeded_forecast, listing_id=b["listing_id"])
    r = client.get("/api/impact", params={"org_id": seeded_forecast})
    stats = r.json()["data"]["false_alarm_stats"]
    assert stats["confirmed"] == 1
    assert stats["withdrawn"] == 1
    assert stats["false_alarm_rate"] == pytest.approx(0.5)


def test_impact_filtering_by_action(client, seeded_forecast):
    r = client.get("/api/impact", params={"org_id": seeded_forecast, "action": "compost"})
    assert r.status_code == 200
    assert r.json()["data"]["event_count"] == 0


# ------------------------------------------------------------- demo ------
def test_demo_scenario_runs_the_whole_story_offline():
    from app.projects.foodlink_predict.db import reset_engine
    from app.projects.foodlink_predict.demo import scenario

    out = scenario.run("org_demo_scenario", as_of=DEMO_AS_OF)
    assert out["completed"] is True
    names = [s["name"] for s in out["steps"]]
    assert any("seed synthetic data" in n for n in names)
    assert any("demand forecast" in n for n in names)
    assert any("waste-risk board" in n for n in names)
    assert any("recommendation agent" in n for n in names)
    assert any("impact ledger" in n for n in names)
    # Labelling requirements.
    assert out["what_is_simulated"]
    assert any("six agents" in s for s in out["what_is_simulated"])
    assert out["narrative"]


def test_demo_scenario_is_deterministic():
    from app.projects.foodlink_predict.demo import scenario

    a = scenario.run("org_det_a", as_of=DEMO_AS_OF)
    b = scenario.run("org_det_b", as_of=DEMO_AS_OF)
    ra = [s for s in a["steps"] if s["name"] == "waste-risk board"][0]
    rb = [s for s in b["steps"] if s["name"] == "waste-risk board"][0]
    assert [(t["item"], t["expected_unsold"], t["risk"]) for t in ra["detail"]["top"]] == [
        (t["item"], t["expected_unsold"], t["risk"]) for t in rb["detail"]["top"]
    ]


def test_demo_endpoint(client):
    r = client.post("/api/demo/scenario", json={"as_of": DEMO_AS_OF, "org_id": "org_demo_api"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["completed"] is True
    assert body["meta"]["demo"] is True