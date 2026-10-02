# Add a new tool / endpoint / page (cheat sheet)

## New tool (<10 lines)
1. Open `backend/app/agents/tools.py`.
2. Add:
```python
from pydantic import BaseModel
from app.agents.tools import register_tool
class Args(BaseModel):
    q: str
@register_tool("my_tool", "what it does", Args)
async def my_tool(q: str) -> str:
    return f"got {q}"
```
3. Test: `python -m pytest backend/tests/test_agents.py -q` (mock mode, offline).
4. Planner auto-lists it via `tool_specs()`; no workflow change needed.

## New endpoint
1. Create `backend/app/api/routes_<name>.py` with `router = APIRouter()`.
2. Register in `backend/app/main.py`: `from app.api.routes_<name> import router as x_router` + `app.include_router(x_router, prefix="/api")`.
3. Document in `docs/api-contract.md`.
4. Add test in `backend/tests/test_api.py` using `TestClient(app)`.
5. Rate limit applies automatically to `/api/solve`, `/api/chat` only; add path in `app/main.py` if needed.

## New page
1. Create `frontend/src/pages/<Name>.jsx` (use `Home.jsx` as template: `useState`, `api.*`, `ErrorBanner`, `ResponseArea`).
2. Simple routing: `frontend/src/App.jsx` renders `Home`; add hash route if needed.
3. API calls only via `frontend/src/services/api.js` — add function there, not scattered `fetch`.
4. Add test `frontend/src/pages/<Name>.test.jsx` (see `Home.test.jsx` mock pattern).
5. Run: `npm run test`, `npm run lint`, `npm run build` from `frontend/`.

## Tomorrow commands
- Backend: `cd backend && python -m pip install -r requirements.txt && uvicorn app.main:app --port 8000`
- Frontend: `cd frontend && npm install && npm run dev`
- Tests: `cd backend && python -m pytest -q` ; `cd frontend && npm run test`
