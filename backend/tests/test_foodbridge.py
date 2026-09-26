import sys
sys.path.insert(0, "C:/Users/akara/hackathon-starter/backend")

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import get_settings
from app.foodbridge.agents import shelter_node
from app.foodbridge.events import get_event_store
from app.foodbridge.models import FoodSurplus, Shelter
from app.foodbridge.scoring import (
    allocate_two_pass,
    compatibility_score,
    distance_score,
    haversine_km,
    normalize_weights,
    score_all,
    shelter_demand,
    urgency_score,
)
from app.foodbridge.store import get_store, reset_store
from app.foodbridge.workflow import build_match_workflow, run_match_workflow

client = TestClient(app)
BASE = "/api/foodbridge"


@pytest.fixture(autouse=True)
def isolated():
    reset_store()
    get_event_store().clear()
    yield
    reset_store()
    get_event_store().clear()


def _initial_state(**overrides):
    store = get_store()
    lot = store.get_surplus("food-001")
    rest = store.get_restaurant(lot.restaurant_id)
    base = {
        "workflow_id": uuid.uuid4().hex,
        "surplus": lot.model_dump(mode="json"),
        "restaurant": rest.model_dump(mode="json"),
        "shelters": [s.model_dump(mode="json") for s in store.list_shelters()],
        "shelter_ids": None,
        "requested_radius_km": 10.0,
        "options": {"max_shelters": None, "include_summary": True},
        "retry_count": 0,
        "events": [],
        "steps": [],
        "status": "running",
    }
    base.update(overrides)
    return base


def _run_match(payload=None):
    # A completed match CONSUMES its lot (consume-on-match), so repeated helper
    # calls in one test would hit 409. reset_store() reseeds demo data (verified:
    # it clears then seed_demo() restores rest-001, 3 shelters, food-001), giving
    # each call a pristine available lot. Tests that create their own lots must
    # call the API directly instead of using this helper.
    reset_store()
    r = client.post(f"{BASE}/match", json=payload or {})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- seed data
def test_seed_restaurant_and_surplus_reads():
    store = get_store()
    rest = store.get_restaurant("rest-001")
    assert rest and rest.name == "Green Leaf Restaurant"
    lot = store.get_surplus("food-001")
    assert lot.meal_count == 80
    assert lot.food_type == "cooked_meals"
    assert lot.dietary_tags == ["vegetarian"]
    assert lot.hours_remaining() > 4.5  # expires ~5h from seed


def test_seed_shelters_match_approved_spec():
    shelters = {s.id: s for s in get_store().list_shelters()}
    assert set(shelters) == {"shelter-a", "shelter-b", "shelter-c"}
    a, b, c = shelters["shelter-a"], shelters["shelter-b"], shelters["shelter-c"]
    assert shelter_demand(a.model_dump()) == 50      # cap 60 - occ 10
    assert shelter_demand(b.model_dump()) == 30      # cap 40 - occ 10
    assert shelter_demand(c.model_dump()) == 70      # cap 80 - occ 10
    assert (a.urgency, b.urgency, c.urgency) == ("high", "medium", "high")
    assert all(s.food_requirements == ["vegetarian"] for s in shelters.values())


def test_haversine_distances_approx_approved():
    rest = get_store().get_restaurant("rest-001")
    d = {
        s.id: haversine_km(rest.lat, rest.lon, s.lat, s.lon)
        for s in get_store().list_shelters()
    }
    assert d["shelter-a"] == pytest.approx(2.1, abs=0.15)
    assert d["shelter-c"] == pytest.approx(3.2, abs=0.15)
    assert d["shelter-b"] == pytest.approx(4.7, abs=0.15)


def test_list_endpoints_shapes():
    assert len(client.get(f"{BASE}/restaurants").json()["restaurants"]) == 1
    assert len(client.get(f"{BASE}/shelters").json()["shelters"]) == 3
    lots = client.get(f"{BASE}/surplus").json()["surplus"]
    assert [l["id"] for l in lots] == ["food-001"]


# ---------------------------------------------------------------- create lot
def test_create_surplus_201_and_listed():
    r = client.post(f"{BASE}/surplus", json={
        "restaurant_id": "rest-001", "meal_count": 25,
        "food_type": "cooked_meals", "dietary_tags": ["vegetarian"],
        "expires_in_hours": 3, "notes": "evening batch",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["success"] is True
    assert body["surplus"]["meal_count"] == 25
    assert body["surplus"]["id"].startswith("food-")
    ids = [l["id"] for l in client.get(f"{BASE}/surplus").json()["surplus"]]
    assert body["surplus"]["id"] in ids


def test_create_surplus_validation_and_404():
    # malformed body -> 422 (pydantic)
    assert client.post(f"{BASE}/surplus", json={"restaurant_id": "rest-001", "meal_count": 0}).status_code == 422
    assert client.post(f"{BASE}/surplus", json={"meal_count": 10}).status_code == 422
    # unknown restaurant -> 404 AppError
    r = client.post(f"{BASE}/surplus", json={"restaurant_id": "nope", "meal_count": 10})
    assert r.status_code == 404
    assert "not found" in r.json()["error"].lower()


# ---------------------------------------------------------------- scoring units
def test_scoring_units_ranges_and_mapping():
    assert distance_score(0.0) == 1.0
    assert distance_score(10.0) == 0.0
    assert 0.0 < distance_score(2.1) < 1.0
    assert urgency_score("high") == 1.0
    assert urgency_score("medium") == 0.6
    assert urgency_score("low") == 0.3
    assert compatibility_score(["vegetarian"], ["vegetarian"]) == 1.0
    assert compatibility_score(["vegetarian"], ["vegan"]) == 0.0
    assert compatibility_score([], ["vegetarian"]) == 0.0
    assert compatibility_score(["vegetarian"], []) == 1.0
    assert 0.0 <= distance_score(4.7) <= 1.0


def test_weight_normalization():
    settings = get_settings()
    raw = settings.matching_weights()
    assert sum(raw.values()) == pytest.approx(1.0)  # approved defaults sum to 1
    w = normalize_weights({"distance": 2, "demand": 1})
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["distance"] == pytest.approx(2 / 3, abs=1e-6)
    uniform = normalize_weights({})   # all zero -> uniform
    assert sum(uniform.values()) == pytest.approx(1.0)
    assert uniform["distance"] == pytest.approx(uniform["expiry"])


def test_capacity_validation_in_allocator():
    ranked = [{"shelter_id": "x", "shelter_name": "X", "demand": 10,
               "distance_km": 1.0, "score": 0.9, "breakdown": {}}]
    alloc, unalloc = allocate_two_pass(100, ranked)
    assert alloc[0]["meals"] == 10      # never exceeds demand
    assert unalloc == 90
    alloc, unalloc = allocate_two_pass(4, ranked)  # never exceeds lot
    assert alloc[0]["meals"] == 4 and unalloc == 0


def test_two_pass_greedy_full_fill_then_partial():
    ranked = [
        {"shelter_id": "big", "shelter_name": "Big", "demand": 70,
         "distance_km": 3.0, "score": 0.8, "breakdown": {}},
        {"shelter_id": "small", "shelter_name": "Small", "demand": 30,
         "distance_km": 4.0, "score": 0.7, "breakdown": {}},
    ]
    alloc, unalloc = allocate_two_pass(80, ranked)
    # pass 1: big needs 70 <= 80 -> full; small needs 30 > 10 left -> skipped
    # pass 2: small gets the 10 remaining
    assert {a["shelter_id"]: a["meals"] for a in alloc} == {"big": 70, "small": 10}
    assert unalloc == 0


# ---------------------------------------------------------------- end-to-end
def test_e2e_match_completed_full_workflow():
    j = _run_match({"surplus_id": "food-001", "requested_radius_km": 10})
    assert j["success"] is True
    assert j["workflow_status"] == "completed"
    assert j["retry_count"] == 0
    assert j["total_allocated"] == 80
    assert j["unallocated"] == 0
    assert j["summary"]
    assert j["error"] is None
    # all six agents ran, in order, all correlated to this workflow
    agents = [e["agent"] for e in j["agent_events"]]
    assert agents == ["coordinator", "restaurant", "shelter", "matching",
                      "logistics", "verification", "coordinator"]
    assert all(e["workflow_id"] == j["workflow_id"] for e in j["agent_events"])
    # logistics produced an ordered route
    batches = j["metadata"]["logistics"]["batches"]
    assert len(batches) == 2
    assert batches[0]["shelter_id"] == "shelter-a"      # nearest first
    assert batches[0]["distance_km"] <= batches[1]["distance_km"]
    assert j["metadata"]["weights"]["distance"] == pytest.approx(0.5)


def test_computed_demo_allocation_regression():
    """Pinned from actual engine output: A=50, B=30, C=0 (never hard-coded in src)."""
    j = _run_match({"surplus_id": "food-001"})
    alloc_map = {a["shelter_id"]: a["meals"] for a in j["allocation"]}
    assert alloc_map == {"shelter-a": 50, "shelter-b": 30}
    assert j["total_allocated"] == 80 and j["unallocated"] == 0
    # ranking regression: C ranks above B under approved weights,
    # but C's full demand (70) does not fit in the 30 left after A takes 50
    store = get_store()
    rest = store.get_restaurant("rest-001").model_dump(mode="json")
    lot = store.get_surplus("food-001").model_dump(mode="json")
    shelters = [s.model_dump(mode="json") for s in store.list_shelters()]
    w = normalize_weights(get_settings().matching_weights())
    ranked = score_all(rest, lot, shelters, w, hours_remaining=5.0)
    assert [r["shelter_id"] for r in ranked] == ["shelter-a", "shelter-c", "shelter-b"]
    assert ranked[0]["score"] > ranked[1]["score"] > ranked[2]["score"]


def test_e2e_deterministic_and_radius_filter():
    first = _run_match({"surplus_id": "food-001"})
    second = _run_match({"surplus_id": "food-001"})
    assert [(a["shelter_id"], a["meals"]) for a in first["allocation"]] == \
           [(a["shelter_id"], a["meals"]) for a in second["allocation"]]
    assert first["workflow_id"] != second["workflow_id"]
    # radius 2.5 km -> only shelter-a eligible, 30 meals stay unallocated
    tight = _run_match({"surplus_id": "food-001", "requested_radius_km": 2.5})
    assert {a["shelter_id"] for a in tight["allocation"]} == {"shelter-a"}
    assert tight["unallocated"] == 30


def test_allocation_respects_capacity_and_compatibility():
    j = _run_match({"surplus_id": "food-001"})
    shelters = {s.id: s for s in get_store().list_shelters()}
    lot = get_store().get_surplus("food-001")
    for a in j["allocation"]:
        s = shelters[a["shelter_id"]]
        assert a["meals"] <= shelter_demand(s.model_dump())
        assert set(s.food_requirements) <= set(lot.dietary_tags)
        # every scored component within [0,1] and weights sum to 1
        assert all(0.0 <= v["score"] <= 1.0 for v in a["breakdown"].values())
        assert sum(v["weight"] for v in a["breakdown"].values()) == pytest.approx(1.0)


# ---------------------------------------------------------------- failures
def test_unknown_surplus_404_and_unknown_shelter_404():
    r = client.post(f"{BASE}/match", json={"surplus_id": "food-does-not-exist"})
    assert r.status_code == 404
    assert "not found" in r.json()["error"].lower()
    r = client.post(f"{BASE}/match", json={"shelter_ids": ["shelter-zzz"]})
    assert r.status_code == 404


def test_malformed_match_request_422():
    assert client.post(f"{BASE}/match", json={"requested_radius_km": -1}).status_code == 422
    assert client.post(f"{BASE}/match", json={"surplus_id": 123}).status_code == 422
    assert client.post(f"{BASE}/match", json={"requested_radius_km": "far"}).status_code == 422


def test_expired_lot_rejected_by_restaurant():
    now = datetime.now(timezone.utc)
    get_store().add_surplus(FoodSurplus(
        id="food-expired", restaurant_id="rest-001", meal_count=10,
        food_type="cooked_meals", dietary_tags=["vegetarian"],
        prepared_at=now - timedelta(hours=6), expires_at=now - timedelta(hours=1),
    ))
    # custom lot lives outside the shared helper's reset_store()
    r = client.post(f"{BASE}/match", json={"surplus_id": "food-expired"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["success"] is False
    assert j["workflow_status"] == "failed"
    assert j["error"]["code"] == "SURPLUS_EXPIRED"
    assert j["retry_count"] == 0   # rejected before matching/verification


def test_shelter_agent_filters_incompatible_candidates():
    store = get_store()
    store.shelters["shelter-vegan"] = Shelter(
        id="shelter-vegan", name="Vegan Only", lat=17.4210, lon=78.4810,
        capacity=20, current_occupancy=0, urgency="high",
        food_requirements=["vegan"],
    )
    updates = shelter_node(_initial_state())
    ids = {c["id"] for c in updates["candidates"]}
    assert "shelter-vegan" not in ids            # incompatible with vegetarian lot
    assert ids == {"shelter-a", "shelter-b", "shelter-c"}


# ---------------------------------------------------------------- retry logic
def test_retry_after_bad_matching_succeeds_with_retry_count_1():
    calls = {"n": 0}

    def flaky_matching(state):
        calls["n"] += 1
        if calls["n"] == 1:
            # deliberately over-allocate to trip verification
            return {"ranked": [], "unallocated": -919, "allocations": [
                {"shelter_id": "shelter-a", "shelter_name": "Shelter A",
                 "meals": 999, "distance_km": 2.11, "score": 0.9, "breakdown": {}},
            ]}
        w = normalize_weights(get_settings().matching_weights())
        ranked = score_all(state["restaurant"], state["surplus"], state["candidates"], w,
                           hours_remaining=float(state.get("hours_remaining") or 0))
        alloc, un = allocate_two_pass(state["surplus"]["meal_count"], ranked)
        return {"ranked": ranked, "allocations": alloc, "unallocated": un}

    wf = build_match_workflow(matching_fn=flaky_matching)
    out = asyncio.run(run_match_workflow(_initial_state(), workflow=wf))
    assert out["status"] == "completed"
    assert out["retry_count"] == 1
    assert calls["n"] == 2                       # exactly two matching attempts
    assert sum(a["meals"] for a in out["allocations"]) == 80


def test_double_failure_bounded_verification_failed():
    calls = {"n": 0}

    def always_bad(state):
        calls["n"] += 1
        return {"ranked": [], "unallocated": -919, "allocations": [
            {"shelter_id": "shelter-a", "shelter_name": "Shelter A",
             "meals": 999, "distance_km": 2.11, "score": 0.9, "breakdown": {}},
        ]}

    wf = build_match_workflow(matching_fn=always_bad)
    out = asyncio.run(run_match_workflow(_initial_state(), workflow=wf))
    assert out["status"] == "failed"
    assert out["error"]["code"] == "VERIFICATION_FAILED"
    assert out["retry_count"] == 1               # bounded: max 1 retry
    assert calls["n"] == 2                       # at most TWO matching attempts
    codes = {i["code"] for i in out["error"]["details"]}
    assert "OVER_DEMAND" in codes and "OVER_TOTAL" in codes


def test_workflow_timeout_returns_timeout_status():
    class _SlowWorkflow:
        async def ainvoke(self, state):
            await asyncio.sleep(5)
            return state

    out = asyncio.run(run_match_workflow(_initial_state(),
                                         workflow=_SlowWorkflow(),
                                         timeout_seconds=0.05))
    assert out["status"] == "timeout"
    assert out["error"]["code"] == "MATCH_TIMEOUT"
    # timeout event still recorded on the bus
    evs = get_event_store().list(workflow_id=out["workflow_id"])
    assert any(e["status"] == "failed" and "timed out" in e["detail"] for e in evs)


# ---------------------------------------------------------------- events / summary
def test_event_correlation_by_workflow_id():
    j = _run_match({"surplus_id": "food-001"})
    wid = j["workflow_id"]
    evs = client.get(f"{BASE}/agents/events", params={"workflow_id": wid}).json()["events"]
    assert evs and all(e["workflow_id"] == wid for e in evs)
    assert {e["agent"] for e in evs} == {"coordinator", "restaurant", "shelter",
                                         "matching", "logistics", "verification"}
    ver = client.get(f"{BASE}/agents/events",
                     params={"workflow_id": wid, "agent": "verification"}).json()["events"]
    assert ver and all(e["agent"] == "verification" for e in ver)
    assert client.get(f"{BASE}/agents/events",
                      params={"workflow_id": "no-such-workflow"}).json()["events"] == []


def test_mock_demo_mode_summary_is_labeled_and_deterministic():
    j = _run_match({"surplus_id": "food-001"})
    assert j["summary"].startswith("[DEMO MODE]")
    assert j["summary_source"] == "deterministic"
    assert j["metadata"]["demo_mode"] is True
    assert j["metadata"]["llm_provider"] == "mock"
    assert j["metadata"]["max_retries"] == 1
    # numbers in the summary must come from the actual allocation
    assert "50 meals" in j["summary"] and "30 meals" in j["summary"]


# ------------------------------------------------- surplus lifecycle (consume-on-match)
def test_full_match_consumes_lot_and_marks_allocated():
    r = client.post(f"{BASE}/match", json={"surplus_id": "food-001"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["success"] is True and j["total_allocated"] == 80
    lot = get_store().get_surplus("food-001")
    assert lot.status == "allocated"      # full consumption -> consumed
    assert lot.meal_count == 80           # original count preserved for audit
    assert j["metadata"]["surplus_status"] == "allocated"
    assert j["metadata"]["surplus_remaining"] == 80


def test_partial_match_decrements_lot_and_leaves_it_available():
    r1 = client.post(f"{BASE}/match", json={"surplus_id": "food-001", "requested_radius_km": 2.5})
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["total_allocated"] == 50    # only shelter-a within 2.5 km
    assert j1["unallocated"] == 30
    lot = get_store().get_surplus("food-001")
    assert lot.status == "available"      # partial -> still matchable
    assert lot.meal_count == 30           # 80 - 50
    assert j1["metadata"]["surplus_status"] == "available"
    assert j1["metadata"]["surplus_remaining"] == 30
    # the remaining 30 meals are matchable afterwards
    r2 = client.post(f"{BASE}/match", json={"surplus_id": "food-001"})
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert j2["success"] is True and j2["total_allocated"] == 30
    assert j2["unallocated"] == 0
    assert {a["shelter_id"] for a in j2["allocation"]} == {"shelter-b"}  # demand 30 fits exactly
    lot = get_store().get_surplus("food-001")
    assert lot.status == "allocated"      # remainder consumed
    assert lot.meal_count == 30           # unchanged once allocated


def test_second_match_on_consumed_lot_409_without_rerun():
    r1 = client.post(f"{BASE}/match", json={"surplus_id": "food-001"})
    assert r1.status_code == 200, r1.text
    events_before = get_event_store().list(limit=1000)
    r2 = client.post(f"{BASE}/match", json={"surplus_id": "food-001"})
    assert r2.status_code == 409
    body = r2.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SURPLUS_ALREADY_ALLOCATED"
    assert body["error"]["surplus_id"] == "food-001"
    assert "workflow_id" not in body       # no workflow produced for the rejection
    # workflow did NOT re-run: identical event set as before the rejected call
    events_after = get_event_store().list(limit=1000)
    assert len(events_after) == len(events_before)
    assert {e["workflow_id"] for e in events_after} == {r1.json()["workflow_id"]}


def test_surplus_list_hides_consumed_lot_unless_include_all():
    r = client.post(f"{BASE}/match", json={"surplus_id": "food-001"})
    assert r.status_code == 200, r.text
    visible = client.get(f"{BASE}/surplus").json()["surplus"]
    assert visible == []                   # consumed lot hidden by default
    all_lots = client.get(f"{BASE}/surplus", params={"include_all": "true"}).json()["surplus"]
    assert [l["id"] for l in all_lots] == ["food-001"]
    assert all_lots[0]["status"] == "allocated"
    assert all_lots[0]["meal_count"] == 80


def test_concurrent_matches_have_single_winner():
    async def fire():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await asyncio.gather(
                ac.post(f"{BASE}/match", json={"surplus_id": "food-001"}),
                ac.post(f"{BASE}/match", json={"surplus_id": "food-001"}),
            )

    r1, r2 = asyncio.run(fire())
    assert sorted(r.status_code for r in (r1, r2)) == [200, 409]
    loser = next(r for r in (r1, r2) if r.status_code == 409)
    assert loser.json()["error"]["code"] in ("SURPLUS_IN_PROGRESS", "SURPLUS_ALREADY_ALLOCATED")
    winner = next(r for r in (r1, r2) if r.status_code == 200)
    assert winner.json()["success"] is True
    assert winner.json()["total_allocated"] == 80   # allocated exactly once, never double
    lot = get_store().get_surplus("food-001")
    assert lot.status == "allocated" and lot.meal_count == 80


def test_demo_reset_reruns_match_live():
    # proof the demo can be re-run in front of judges without a server restart
    assert client.post(f"{BASE}/match", json={"surplus_id": "food-001"}).status_code == 200
    assert client.post(f"{BASE}/match", json={"surplus_id": "food-001"}).status_code == 409
    r = client.post(f"{BASE}/demo/reset")
    assert r.status_code == 200
    assert r.json() == {"success": True, "message": "Demo data reset"}
    lots = client.get(f"{BASE}/surplus").json()["surplus"]
    assert [(l["id"], l["status"], l["meal_count"]) for l in lots] == [("food-001", "available", 80)]
    again = client.post(f"{BASE}/match", json={"surplus_id": "food-001"})
    assert again.status_code == 200, again.text
    assert again.json()["success"] is True and again.json()["total_allocated"] == 80
