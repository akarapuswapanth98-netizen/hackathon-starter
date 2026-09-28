# CLAUDE.md

> Quick reference for AI assistants working on hackathon-starter

## Project Overview

**hackathon-starter** is a full-stack TypeScript/Python monorepo for rapid hackathon development. FastAPI backend with LangGraph multi-agent workflows (FoodBridge) + Vite/React frontend.

For detailed guidelines, see [AGENTS.md](AGENTS.md).

## Quick Commands

```bash
# Backend
cd backend
python -m pytest tests/ -q              # Run tests (51 expected)
uvicorn app.main:app --port 8000        # Start server

# Frontend
cd frontend
npm run dev         # Dev server at localhost:5173
npm run build       # Production build
npm run lint        # ESLint

# Full demo (from root)
make demo           # Linux/macOS
.\demo.ps1          # Windows PowerShell
```

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/foodbridge/agents.py` | 6 agents + terminals |
| `backend/app/foodbridge/workflow.py` | LangGraph + fallback |
| `backend/app/foodbridge/store.py` | In-memory store + lifecycle |
| `backend/app/foodbridge/scoring.py` | Pure matching math |
| `backend/app/api/routes_foodbridge.py` | HTTP endpoints |
| `backend/app/core/config.py` | All settings |
| `backend/tests/test_foodbridge.py` | 45 FoodBridge tests |
| `backend/tests/test_openapi_contract.py` | 6 contract tests |
| `docs/foodbridge.md` | Architecture docs |
| `docs/api-contract.md` | API contract |
| `frontend/src/services/api.js` | API client |

## FoodBridge Endpoints

```
GET  /api/foodbridge/restaurants
GET  /api/foodbridge/shelters
GET  /api/foodbridge/surplus?include_all=false
POST /api/foodbridge/surplus          # 201
POST /api/foodbridge/match            # 200 or 409
GET  /api/foodbridge/agents/events
POST /api/foodbridge/demo/reset       # Demo only
```

## Code Patterns

### Python
- Type hints everywhere (strict)
- Pure functions for agents, TypedDict state
- Pydantic v2 for all API schemas
- In-memory store with lifecycle (consume-on-match)

### React/TypeScript
- Single API client in `src/services/api.js`
- Page-level data fetching
- ESLint + TypeScript strict

## Before Committing

1. Backend: `cd backend && python -m pytest tests/ -q` (51 passing)
2. Frontend: `cd frontend && npm run lint`
3. Never commit secrets (use `.env`)

## Environment

Backend `.env`:
```bash
LLM_PROVIDER=mock          # mock | openai | groq | anthropic | gemini
LLM_API_KEY=               # Required for real providers
MATCH_W_DISTANCE=0.50
MATCH_W_DEMAND=0.10
MATCH_W_URGENCY=0.15
MATCH_W_CAPACITY=0.05
MATCH_W_COMPATIBILITY=0.10
MATCH_W_EXPIRY=0.10
MATCH_TIMEOUT_SECONDS=10
MATCH_MAX_RETRIES=1
FOODBRIDGE_DEMO_MODE=auto
```

## Demo Flow

```bash
# 1. Start backend
cd backend && uvicorn app.main:app --port 8000

# 2. Run match (consumes lot)
curl -X POST http://localhost:8000/api/foodbridge/match \
  -H "Content-Type: application/json" \
  -d '{"surplus_id":"food-001"}'

# 3. Repeat match → 409 (lot consumed)
# 4. Reset demo
curl -X POST http://localhost:8000/api/foodbridge/demo/reset

# 5. Match again → success
```

## Project Structure

```
backend/
├── app/foodbridge/     # Multi-agent system
│   ├── agents.py       # 6 agents + terminals
│   ├── workflow.py     # LangGraph + fallback
│   ├── store.py        # In-memory + lifecycle
│   ├── scoring.py      # Deterministic math
│   └── models.py       # Pydantic schemas
├── api/routes_foodbridge.py
├── core/config.py
└── tests/              # 51 tests

frontend/
├── src/services/api.js  # Single API client
├── src/pages/           # Page components
└── src/components/      # Reusable components
```