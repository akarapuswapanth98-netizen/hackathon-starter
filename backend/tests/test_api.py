import sys
sys.path.insert(0, "C:/Users/akara/hackathon-starter/backend")

from fastapi.testclient import TestClient
from app.main import app
import pytest

client = TestClient(app)

def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert "llm_provider" in j
    assert "rag_enabled" in j

def test_health_db():
    r = client.get("/api/health/db")
    assert r.status_code == 200
    assert "enabled" in r.json()

def test_chat_success():
    r = client.post("/api/chat", json={"message": "Hello"})
    assert r.status_code == 200
    j = r.json()
    assert "reply" in j
    assert j["reply"]  # not empty
    assert "provider" in j

def test_chat_validation_missing_message():
    r = client.post("/api/chat", json={})
    assert r.status_code == 422

def test_chat_validation_empty():
    r = client.post("/api/chat", json={"message": ""})
    assert r.status_code == 422

def test_solve_success_query():
    r = client.post("/api/solve", json={"query": "Explain AI for hackathon demo", "context": "test"})
    assert r.status_code == 200
    j = r.json()
    assert j["success"] is True
    assert j["answer"]
    assert j["confidence"] is None  # per spec, null if not calculated

def test_solve_success_problem_alias():
    r = client.post("/api/solve", json={"problem": "Test via problem alias"})
    assert r.status_code == 200
    assert r.json()["success"] is True

def test_solve_validation_missing():
    r = client.post("/api/solve", json={})
    assert r.status_code == 422

def test_solve_with_agents_false():
    r = client.post("/api/solve", json={"query": "Direct LLM", "use_agents": False})
    assert r.status_code == 200
    assert r.json()["success"] is True

def test_upload_invalid_type():
    # Upload unsupported file type
    files = {"file": ("bad.exe", b"fake", "application/octet-stream")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 400

def test_rag_disabled_returns_error_on_chat_rag():
    r = client.post("/api/chat", json={"message": "test", "use_rag": True})
    # RAG_ENABLED=false by default, should error
    assert r.status_code == 400
    assert "RAG disabled" in r.json()["detail"]

def test_validator_behavior_via_solve():
    # Solve should include reasoning_steps
    r = client.post("/api/solve", json={"query": "Short"})
    assert r.status_code == 200
    j = r.json()
    assert "reasoning_steps" in j
    assert isinstance(j["reasoning_steps"], list)

def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "message" in r.json()
