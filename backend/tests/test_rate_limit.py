import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _restore_rate_limit_env():
    old = os.environ.get("RATE_LIMIT_PER_MIN")
    yield
    if old is None:
        os.environ.pop("RATE_LIMIT_PER_MIN", None)
    else:
        os.environ["RATE_LIMIT_PER_MIN"] = old
    from app.core.config import get_settings
    get_settings.cache_clear()


def _client_with_limit(limit: str):
    os.environ["RATE_LIMIT_PER_MIN"] = limit
    os.environ["LLM_PROVIDER"] = "mock"
    from app.core.config import get_settings
    get_settings.cache_clear()
    # Rebuild app so middleware picks up fresh settings per request (middleware reads get_settings live,
    # but rebuild isolates the in-memory hit buckets between tests).
    from app.main import create_app
    return TestClient(create_app())


def test_rate_limit_disabled_when_zero():
    c = _client_with_limit("0")
    for _ in range(5):
        r = c.post("/api/chat", json={"message": "hi"})
        assert r.status_code == 200
    from app.core.config import get_settings
    assert get_settings().RATE_LIMIT_PER_MIN == 0


def test_rate_limit_enforced_when_low():
    c = _client_with_limit("2")
    assert c.post("/api/chat", json={"message": "hi"}).status_code == 200
    assert c.post("/api/chat", json={"message": "hi"}).status_code == 200
    r = c.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 429
    assert "Rate limited" in r.text
