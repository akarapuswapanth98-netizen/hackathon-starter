"""Preflight checks for hackathon demo day. Runs in under 10 seconds.
Usage: python scripts/preflight.py  (run from repo root or backend/)
Prints PASS/FAIL per check plus the exact fix for each FAIL. Exit 0 if all pass, 1 otherwise.
"""
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

results = []


def check(name, ok, fix=""):
    results.append((name, bool(ok), fix))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"  -> fix: {fix}"))


def main():
    # 1. Python version
    check("Python >=3.13", sys.version_info >= (3, 13),
          f"install Python 3.13 (found {sys.version.split()[0]})")
    # 2. Node available
    import shutil
    node = shutil.which("node") or shutil.which("node.exe")
    check("Node installed", node is not None, "install Node 20+ from nodejs.org")
    # 3. Python deps
    missing = []
    for mod in ("fastapi", "uvicorn", "pydantic", "pytest", "langgraph"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    check("pip deps installed", not missing,
          f"cd backend && python -m pip install -r requirements.txt (missing: {', '.join(missing)})")
    # 4. .env present (optional but warn)
    env_path = os.path.join(BACKEND, ".env")
    has_env = os.path.exists(env_path)
    provider = os.getenv("LLM_PROVIDER", "mock (default)")
    check(".env present (optional, mock works without it)", has_env,
          "copy backend/.env.example to backend/.env (mock mode works without it)")
    print(f"      LLM_PROVIDER={provider} (mock needs no key; groq/gemini need GROQ_API_KEY/GEMINI_API_KEY in backend/.env)")
    # 5. Ports free
    for port in (8000, 5173):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            free = True
        except OSError:
            free = False
        finally:
            s.close()
        check(f"port {port} free", free,
              f"another app uses {port}: stop it or run uvicorn/vite with --port <other>")
    # 6. Backend health + mock solve (in-process, no server needed)
    try:
        os.environ.setdefault("LLM_PROVIDER", "mock")
        from app.core.config import get_settings
        get_settings.cache_clear()
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        r = c.get("/api/health")
        check("backend /api/health reachable", r.status_code == 200,
              "cd backend && python -m pip install -r requirements.txt, then check logs")
        r2 = c.post("/api/solve", json={"query": "preflight check", "use_agents": True})
        ok = r2.status_code == 200 and bool(r2.json().get("answer"))
        check("mock /api/solve succeeds", ok,
              "cd backend && python -m pytest -q (see failures)")
    except Exception as e:
        check("backend reachable", False, f"import/start failed: {e}")

    failed = [n for n, ok, _ in results if not ok]
    # .env missing is advisory (mock works), don't fail the run for it.
    hard_fail = [n for n in failed if not n.startswith(".env present")]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
