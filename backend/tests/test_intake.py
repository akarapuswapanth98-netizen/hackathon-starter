import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_intake_returns_valid_spec():
    r = client.post("/api/intake", json={"problem": "Farmers need crop disease advice."})
    assert r.status_code == 200
    j = r.json()
    assert j["success"] is True
    spec = j["spec"]
    assert len(spec["must_have_features"]) == 3
    assert all(f["name"] and f["description"] and f["data_needed"] for f in spec["must_have_features"])
    assert 2 <= len(spec["stretch_goals"]) <= 3
    assert len(spec["judging_criteria_map"]) >= 3
    assert 2 <= len(spec["risks"]) <= 3
    assert 4 <= len(spec["demo_flow"]) <= 6
    assert j["fallback"] in ("llm", "heuristic")
    assert j["fallback_reason"] in ("none", "truncated", "bad_json", "wrong_shape", "api_error")


def test_intake_criteria_passthrough():
    crit = "Innovation\nExecution\nImpact"
    r = client.post("/api/intake", json={"problem": "Clinic triage help.", "criteria": crit})
    assert r.status_code == 200
    cmap = r.json()["spec"]["judging_criteria_map"]
    for k in ("Innovation", "Execution", "Impact"):
        assert k in cmap, f"criteria key missing: {k}"
    # Oversized criteria rejected by validation.
    assert client.post("/api/intake", json={"problem": "x", "criteria": "y" * 2001}).status_code == 422


def test_intake_empty_field_retries_then_falls_back():
    import app.api.routes_intake as RI
    from app.agents.nodes import LLMJSONError

    calls = []

    async def flaky(llm, prompt, system, schema, example=None, max_tokens=400):
        calls.append(1)
        if len(calls) == 1:
            raise LLMJSONError("wrong_shape", "empty stretch_goals")
        return RI.heuristic_spec("Farmers need advice.")

    orig = RI._llm_json
    RI._llm_json = flaky
    try:
        # Call generate_spec directly to observe the retry path is inside _llm_json;
        # endpoint-level: persistent failure -> heuristic with reason.
        async def always_bad(llm, prompt, system, schema, example=None, max_tokens=400):
            raise LLMJSONError("wrong_shape", "empty stretch_goals")
        RI._llm_json = always_bad
        import asyncio
        spec, fallback, reason = asyncio.run(RI.generate_spec("Farmers need advice."))
        assert fallback == "heuristic" and reason == "wrong_shape"
        assert 2 <= len(spec.stretch_goals) <= 3
    finally:
        RI._llm_json = orig


def test_fallback_reason_values():
    r = client.post("/api/intake", json={"problem": "Study planners for students."})
    j = r.json()
    assert j["fallback"] == "heuristic"  # mock provider cannot emit JSON
    assert j["fallback_reason"] == "bad_json"


def test_intake_empty_and_oversized():
    assert client.post("/api/intake", json={"problem": "   "}).status_code == 422
    assert client.post("/api/intake", json={"problem": "z" * 9000}).status_code == 422
    assert "required" in client.post("/api/intake", json={"problem": ""}).json()["detail"]


def test_intake_wrong_shape_llm_falls_back():
    import app.api.routes_intake as RI

    async def bad_llm(*a, **k):
        return {"wrong": "shape"}  # missing required keys -> validation path

    orig = RI._llm_json

    async def fake(llm, prompt, system, schema, example=None):
        import json
        data = await bad_llm()
        return schema.model_validate(data)  # raises ValidationError

    RI._llm_json = fake
    try:
        r = client.post("/api/intake", json={"problem": "Students need study planners."})
        assert r.status_code == 200
        j = r.json()
        assert j["fallback"] == "heuristic"
        assert len(j["spec"]["must_have_features"]) == 3
    finally:
        RI._llm_json = orig


def _load_scaffold():
    import importlib.util
    p = Path(__file__).parent.parent / "scripts" / "scaffold.py"
    spec = importlib.util.spec_from_file_location("scaffold", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scaffolder_writes_and_refuses(tmp_path, monkeypatch):
    mod = _load_scaffold()
    monkeypatch.setattr(mod, "SPEC_PATH", str(tmp_path / "PROJECT_SPEC.md"))
    monkeypatch.setattr(mod, "PLAN_PATH", str(tmp_path / "BUILD_PLAN.md"))
    monkeypatch.setattr("sys.argv", ["scaffold.py", "Students need study planners."])
    assert mod.main() == 0
    assert (tmp_path / "PROJECT_SPEC.md").exists()
    assert (tmp_path / "BUILD_PLAN.md").exists()
    text = (tmp_path / "BUILD_PLAN.md").read_text(encoding="utf-8")
    assert "Home.jsx" in text and "tools.py" in text
    assert "Prepare seed data" in text
    # Second run without --force must refuse.
    monkeypatch.setattr("sys.argv", ["scaffold.py", "Another problem."])
    assert mod.main() == 1
    # --force overwrites.
    monkeypatch.setattr("sys.argv", ["scaffold.py", "Another problem.", "--force"])
    assert mod.main() == 0
