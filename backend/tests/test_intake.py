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
    assert all(f["name"] and f["description"] for f in spec["must_have_features"])
    assert 4 <= len(spec["demo_flow"]) <= 6
    assert len(spec["risks"]) <= 3 and len(spec["stretch_goals"]) <= 3
    assert j["fallback"] in ("llm", "heuristic")


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
    # Second run without --force must refuse.
    monkeypatch.setattr("sys.argv", ["scaffold.py", "Another problem."])
    assert mod.main() == 1
    # --force overwrites.
    monkeypatch.setattr("sys.argv", ["scaffold.py", "Another problem.", "--force"])
    assert mod.main() == 0
