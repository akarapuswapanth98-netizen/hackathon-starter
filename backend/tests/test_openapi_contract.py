"""Contract tests - validate FoodBridge endpoints against OpenAPI schema."""
import sys
sys.path.insert(0, "C:/Users/akara/hackathon-starter/backend")

import pytest
import json
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_openapi_schema_exists():
    """OpenAPI schema is generated and valid."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert "openapi" in schema
    assert "Hackathon Starter" in schema["info"]["title"]


def test_foodbridge_endpoints_documented():
    """All FoodBridge routes appear in OpenAPI schema."""
    schema = client.get("/openapi.json").json()
    paths = schema.get("paths", {})

    # Required FoodBridge endpoints (tags=["foodbridge"])
    expected = {
        "GET": ["/api/foodbridge/restaurants", "/api/foodbridge/shelters",
                "/api/foodbridge/surplus", "/api/foodbridge/agents/events"],
        "POST": ["/api/foodbridge/surplus", "/api/foodbridge/match",
                 "/api/foodbridge/demo/reset"],
    }

    for method, endpoints in expected.items():
        for ep in endpoints:
            assert ep in paths, f"Missing {ep} in OpenAPI"
            assert method.lower() in paths[ep], f"Missing {method} on {ep}"
            # Verify foodbridge tag present
            op = paths[ep][method.lower()]
            assert "foodbridge" in op.get("tags", []), f"{method} {ep} missing foodbridge tag"


def test_match_response_schema():
    """POST /match response matches MatchResponse model."""
    r = client.post("/api/foodbridge/match", json={"surplus_id": "food-001"})
    assert r.status_code == 200
    data = r.json()

    # Required keys from MatchResponse
    required = ["success", "workflow_id", "workflow_status", "allocation",
                "agent_events", "total_allocated", "unallocated",
                "summary", "summary_source", "retry_count", "metadata", "error"]
    for k in required:
        assert k in data, f"Missing {k} in match response"

    # allocation is list of Allocation objects
    assert isinstance(data["allocation"], list)
    for a in data["allocation"]:
        for k in ["shelter_id", "shelter_name", "meals", "distance_km", "score", "breakdown"]:
            assert k in a, f"Allocation missing {k}"

    # agent_events are AgentEvent objects
    assert isinstance(data["agent_events"], list)
    for e in data["agent_events"]:
        for k in ["workflow_id", "agent", "status", "detail", "timestamp"]:
            assert k in e, f"AgentEvent missing {k}"

    # metadata includes our additions
    assert "surplus_status" in data["metadata"]
    assert "surplus_remaining" in data["metadata"]


def test_404_returns_apperror_shape():
    """Unknown surplus returns AppError shape (not 200)."""
    r = client.post("/api/foodbridge/match", json={"surplus_id": "food-does-not-exist"})
    assert r.status_code == 404
    data = r.json()
    assert "error" in data
    assert "detail" in data
    assert "path" in data


def test_demo_reset_response_shape():
    """POST /demo/reset returns documented shape."""
    r = client.post("/api/foodbridge/demo/reset")
    assert r.status_code == 200
    data = r.json()
    assert data == {"success": True, "message": "Demo data reset"}


def test_surplus_list_includes_all_param():
    """GET /surplus accepts include_all parameter."""
    r = client.get("/api/foodbridge/surplus?include_all=true")
    assert r.status_code == 200
    data = r.json()
    assert "surplus" in data
    assert isinstance(data["surplus"], list)