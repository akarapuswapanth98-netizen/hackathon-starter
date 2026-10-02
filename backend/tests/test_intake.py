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


def _core_partial():
    return {
        "title": "Clinic Helper",
        "target_user": "Clinic staff",
        "core_problem": "Triage patient messages quickly",
        "must_have_features": [
            {"name": "F1", "description": "d1", "data_needed": "seed1"},
            {"name": "F2", "description": "d2", "data_needed": "seed2"},
            {"name": "F3", "description": "d3", "data_needed": "seed3"},
        ],
        "stretch_goals": [],
        "demo_flow": ["s1", "s2", "s3", "s4"],
        "judging_criteria_map": {},
        "suggested_tools": ["text_search"],
        "risks": [],
    }


def test_partial_repair_keeps_core():
    import asyncio
    import app.api.routes_intake as RI
    from app.agents.nodes import LLMJSONError

    async def flaky(llm, prompt, system, schema, example=None, max_tokens=400):
        if schema.__name__ == "ProjectSpec":
            raise LLMJSONError("wrong_shape", "empty lists", partial=_core_partial())
        # Repair call: return valid gap fill.
        return schema.model_validate({
            "stretch_goals": ["Voice input", "SMS alerts"],
            "judging_criteria_map": {"A": "x", "B": "y", "C": "z"},
            "risks": ["r1", "r2"],
        })

    orig = RI._llm_json
    RI._llm_json = flaky
    try:
        spec, fallback, reason = asyncio.run(RI.generate_spec("Clinic triage help."))
        assert fallback == "partial_repair" and reason == "wrong_shape"
        assert spec.title == "Clinic Helper"  # original core kept
        assert [f.name for f in spec.must_have_features] == ["F1", "F2", "F3"]
        assert spec.stretch_goals == ["Voice input", "SMS alerts"]  # repaired, not defaults
    finally:
        RI._llm_json = orig


def test_repair_failure_uses_defaults():
    import asyncio
    import app.api.routes_intake as RI
    from app.agents.nodes import LLMJSONError

    async def always_bad(llm, prompt, system, schema, example=None, max_tokens=400):
        raise LLMJSONError("wrong_shape", "empty", partial=_core_partial())

    orig = RI._llm_json
    RI._llm_json = always_bad
    try:
        spec, fallback, reason = asyncio.run(RI.generate_spec("Clinic triage help."))
        assert fallback == "partial_repair"
        assert spec.title == "Clinic Helper"
        assert spec.stretch_goals == ["Local-language input", "Voice input"]  # deterministic defaults
        assert len(spec.judging_criteria_map) == 3 and len(spec.risks) == 3
    finally:
        RI._llm_json = orig


def test_full_heuristic_only_when_core_invalid():
    import asyncio
    import app.api.routes_intake as RI
    from app.agents.nodes import LLMJSONError

    bad = _core_partial()
    bad["must_have_features"] = bad["must_have_features"][:2]  # core invalid

    async def bad_core(llm, prompt, system, schema, example=None, max_tokens=400):
        raise LLMJSONError("wrong_shape", "short features", partial=bad)

    orig = RI._llm_json
    RI._llm_json = bad_core
    try:
        spec, fallback, reason = asyncio.run(RI.generate_spec("Clinic triage help."))
        assert fallback == "heuristic" and reason == "wrong_shape"
        assert len(spec.must_have_features) == 3
    finally:
        RI._llm_json = orig


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
