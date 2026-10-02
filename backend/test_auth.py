"""Smoke script for auth OFF default + health/root."""
import sys
sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

print("Testing authentication defaults...")

from app.core.config import get_settings
s = get_settings()
print(f"AUTH_ENABLED: {s.AUTH_ENABLED}")
assert s.AUTH_ENABLED is False, "AUTH_ENABLED must default to False"

r = client.get("/api/health")
print(f"GET /api/health: status={r.status_code}, body={r.json()}")
assert r.status_code == 200

r = client.get("/")
print(f"GET /: status={r.status_code}, body={r.json()}")
assert r.status_code == 200

print("\nAuthentication default test PASSED!")
