import sys
sys.path.insert(0, "C:/Users/akara/hackathon-starter/backend")
import asyncio
from app.agents.workflow import run_workflow

def test_workflow_success():
    r = asyncio.run(run_workflow("Explain FastAPI", "hackathon context"))
    assert "final" in r
    assert r["final"]
    assert "steps" in r
    assert len(r["steps"]) >= 3

def test_workflow_with_rag_context():
    r = asyncio.run(run_workflow("Test", rag_context="RAG docs here"))
    assert "tool_output" in r or "rag_context" in r
    assert r["final"]

def test_workflow_planner_reasoner_validator():
    r = asyncio.run(run_workflow("Test validation"))
    # Validator should set passed flag
    assert r["metadata"]["validator_passed"] is True
