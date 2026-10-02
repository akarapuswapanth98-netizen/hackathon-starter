# Add a new tool / endpoint / page (cheat sheet — corrected after dry run)

## New tool (2 edits, not 1)
1. Open `backend/app/agents/tools.py` and append (<10 lines):
```python
class Args(BaseModel):  # BaseModel already imported in tools.py
    message: str
@register_tool("classify_urgency", "Classify a clinic message as critical/high/normal.", Args)
async def classify_urgency(message: str) -> str:
    t = message.lower()
    if "chest pain" in t:
        return "urgency=critical reason=red-flag symptom"
    return "urgency=normal reason=routine"
```
2. REQUIRED second edit — mock executor does NOT auto-call new tools. Open `backend/app/agents/nodes.py`,
   find the `if _is_mock():` block in `executor_node`, and add one `elif` before the `else: done` branch:
```python
elif "classify_urgency" not in done_names and "clinic" in problem.lower():
    tool, args = "classify_urgency", {"message": problem[:500]}
```
   (Real-LLM mode picks tools from `tool_specs()` automatically; mock mode needs this rule.
   For one-off verification you can also call it directly: `await call_tool("classify_urgency", {...})`.)
3. Optional prompt tweak: edit `SYSTEM_REASONER` in `backend/app/ai/prompts.py`, or the
   `CLINIC_REASONER_SUFFIX`-style constant in `nodes.py`, so the final answer mentions the tool result.
4. Test from `backend/` (NOT repo root): `cd backend && python -m pytest tests/test_agents.py -q`
   (mock mode, offline). Async tools need `asyncio.run(...)` in tests.
5. Verify routing: `run_workflow("...clinic...")` should list your tool in `tool_calls`.

## New endpoint
1. Create `backend/app/api/routes_<name>.py` with `router = APIRouter()`.
2. Register in `backend/app/main.py`: import + `app.include_router(x_router, prefix="/api")`.
3. Document in `docs/api-contract.md`.
4. Add test in `backend/tests/test_api.py` using `TestClient(app)` (note: `app` object is
   created at import time — set env vars + `get_settings.cache_clear()` BEFORE importing `app`).
5. Rate limit: only `/api/solve`, `/api/solve/stream`, `/api/chat` are limited (see `RATE_LIMIT_PER_MIN`
   in `backend/.env.example`, default 600, 0 disables). Add your path in `app/main.py` if needed.

## New page / section (no router installed)
1. There is NO react-router — `frontend/src/App.jsx` renders `<Home />` only. For speed, add a
   SECTION to `frontend/src/pages/Home.jsx` (like the dry-run `UrgencyCard` reading `trace`),
   instead of a new page. If you truly need a page, install a router yourself.
2. Read tool results from the `trace` prop: `(trace||[]).find(t => t.tool_name === 'my_tool')`.
   Note `output_summary` is truncated to ~120 chars — parse short `key=value` strings, not long JSON.
3. API calls only via `frontend/src/services/api.js`. If you add a function there, update the
   `vi.mock('../services/api', ...)` block in `frontend/src/pages/Home.test.jsx` or tests fail.
4. Run from `frontend/`: `npm run test`, `npm run lint`, `npm run build`.

## Tomorrow commands
- Backend: `cd backend && python -m pip install -r requirements.txt && uvicorn app.main:app --port 8000`
  (restart server after ANY `.env` change — settings snapshot at import)
- Frontend: `cd frontend && npm install && npm run dev`
- Tests: `cd backend && python -m pytest -q` ; `cd frontend && npm run test`
- Preflight: `python scripts/preflight.py` (or `powershell -File scripts/preflight.ps1`)
