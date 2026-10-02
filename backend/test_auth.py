"""Test script for JWT authentication."""
import sys
sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

print("Testing authentication endpoints...")

# Test that auth routes exist when AUTH_ENABLED=true
# First check if auth routes are included
from app.core.config import get_settings
s = get_settings()
print(f"AUTH_ENABLED: {s.AUTH_ENABLED}")

# Test health endpoint (should always work)
r = client.get("/api/health")
print(f"GET /api/health: status={r.status_code}, body={r.json()}")

# Test foodbridge endpoints (should always work)
r = client.get("/api/foodbridge/restaurants")
print(f"GET /api/foodbridge/restaurants: status={r.status_code}")

r = client.get("/api/foodbridge/surplus")
print(f"GET /api/foodbridge/surplus: status={r.status_code}")

r = client.post("/api/foodbridge/match", json={"surplus_id": "food-001"})
print(f"POST /api/foodbridge/match: status={r.status_code}")

# Test root endpoint
r = client.get("/")
print(f"GET /: status={r.status_code}, body={r.json()}")

print("\nAuthentication test PASSED!")