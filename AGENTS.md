# AGENTS.md

> Guidelines for AI coding agents working on this project.

## Project Overview

**hackathon-starter** is a full-stack TypeScript monorepo for rapid hackathon development. It includes a FastAPI backend with LangGraph multi-agent workflows and a Vite/React frontend.

### Tech Stack

- **Backend:** Python 3.13, FastAPI 0.141, LangGraph 1.2, Pydantic 2.13, Uvicorn 0.54
- **Frontend:** React 18.3, Vite 5.4, TypeScript 5, ESLint 8.57
- **Database:** In-memory (FoodBridge) / PostgreSQL-ready
- **AI/ML:** LangChain Core 1.6, LangGraph, configurable LLM providers (OpenAI, Groq, Anthropic, Gemini)
- **Testing:** pytest 9.1 (backend), Vitest 1.6 (frontend)
- **Build:** Make, PowerShell scripts

## Project Structure

```
/
├── backend/                    # FastAPI application
│   ├── app/
│   │   ├── api/               # API routes
│   │   │   ├── routes_foodbridge.py   # FoodBridge endpoints
│   │   │   ├── routes_health.py       # Health checks
│   │   │   ├── routes_chat.py         # Chat endpoints
│   │   │   ├── routes_solve.py        # Problem solving
│   │   │   └── routes_upload.py       # File upload
│   │   ├── core/              # Core configuration
│   │   │   ├── config.py      # Settings management
│   │   │   └── errors.py      # Error handling
│   │   ├── foodbridge/        # FoodBridge multi-agent system
│   │   │   ├── agents.py      # 6 LangGraph agents + terminals
│   │   │   ├── events.py      # Event bus
│   │   │   ├── models.py      # Pydantic models
│   │   │   ├── prompts.py     # Prompt templates
│   │   │   ├── scoring.py     # Deterministic matching math
│   │   │   ├── state.py       # TypedDict state
│   │   │   ├── store.py       # In-memory store + lifecycle
│   │   │   └── workflow.py    # LangGraph StateGraph
│   │   ├── models/            # Shared Pydantic models
│   │   └── main.py            # FastAPI app factory
│   ├── tests/                 # Backend tests
│   ├── requirements.txt       # Python dependencies
│   └── pyproject.toml         # Package config
├── frontend/                   # React application
│   ├── src/
│   │   ├── components/        # React components
│   │   ├── pages/             # Page components
│   │   ├── services/          # API client
│   │   └── hooks/             # Custom hooks
│   ├── package.json
│   └── vite.config.ts
├── docs/                       # Documentation
│   ├── foodbridge.md          # FoodBridge architecture
│   └── api-contract.md        # API contract
├── .github/                    # GitHub workflows
│   ├── workflows/ci.yml       # CI pipeline
│   └── dependabot.yml         # Dependency updates
├── .devcontainer/              # VS Code DevContainer
├── Makefile                    # Demo commands
├── demo.ps1                    # Windows demo script
├── AGENTS.md                   # This file
├── CLAUDE.md                   # AI assistant quick ref
└── README.md
```

## Commands

```bash
# Backend
cd backend
python -m venv venv && . venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests/ -q                  # Run all tests
python -m pytest tests/test_foodbridge.py -q # FoodBridge tests only
uvicorn app.main:app --port 8000            # Start server

# Frontend
cd frontend
npm install
npm run dev          # Start dev server (localhost:5173)
npm run build        # Production build
npm run lint         # Run ESLint

# Full demo (from root)
make demo            # Full match->reset->match cycle
./demo.ps1           # Windows PowerShell demo
```

## Code Style Guidelines

### Python (Backend)

- Use Type Hints everywhere (strict mode via pyproject.toml)
- Prefer `interface`/`Protocol` for object shapes, `type` for unions
- Functions: `snake_case` (e.g., `run_match_workflow`, `get_store`)
- Classes: `PascalCase` (e.g., `FoodBridgeStore`, `MatchRequest`)
- Constants: `UPPER_SNAKE_CASE` for true constants
- Files: `snake_case.py`
- Use Pydantic v2 models for all API schemas

### TypeScript/React (Frontend)

- Use TypeScript strict mode
- Prefer explicit types over `any`
- Use `interface` for object shapes, `type` for unions/intersections
- Functions/Variables: `camelCase` (e.g., `fetchRestaurants`, `handleSubmit`)
- Components: `PascalCase` (e.g., `FoodBridgeDashboard`, `ShelterCard`)
- Constants: `UPPER_SNAKE_CASE` for true constants
- Files: `PascalCase.tsx` for components, `camelCase.ts` for utilities

### Architecture Patterns

- **Backend:** Pure functions for agents, TypedDict for state, single event bus
- **Frontend:** Single API client in `src/services/api.js`, page-level data fetching
- **Tests:** Place in `backend/tests/`, use `fastapi.testclient.TestClient`
- **Config:** Environment-driven via `.env` (never commit secrets)

## Configuration

### Backend Environment Variables (`.env`)

```bash
# Core
LLM_PROVIDER=mock              # mock | openai | groq | anthropic | gemini
LLM_API_KEY=                   # Required for real providers
LLM_MODEL=gpt-4o-mini          # Model name

# FoodBridge Matching Weights (normalized to sum 1.0 at runtime)
MATCH_W_DISTANCE=0.50
MATCH_W_DEMAND=0.10
MATCH_W_URGENCY=0.15
MATCH_W_CAPACITY=0.05
MATCH_W_COMPATIBILITY=0.10
MATCH_W_EXPIRY=0.10
MATCH_TIMEOUT_SECONDS=10
MATCH_MAX_RETRIES=1
FOODBRIDGE_DEMO_MODE=auto      # auto | true | false

# Optional
API_TIMEOUT=30
ENABLE_RAG=false
ENABLE_DB=false
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Frontend Environment Variables (`.env`)

```bash
VITE_API_URL=http://localhost:8000/api
```

## FoodBridge Multi-Agent System

### The 6 Agents

1. **Coordinator** - Validates request, initializes workflow
2. **Restaurant** - Loads surplus lot, computes `hours_remaining`
3. **Shelter** - Filters candidates: radius, dietary compatibility, demand
4. **Matching** - Deterministic weighted scores + two-pass greedy allocation
5. **Logistics** - Ordered delivery batches (nearest first), ETA
6. **Verification** - Hard-constraint audit; grants bounded retry

### Terminal Nodes

- `coordinator_final_node` - LLM summary (demo: deterministic template)
- `coordinator_error_node` - Structured failure response

### Retry Logic

- Bounded by `MATCH_MAX_RETRIES` (default 1)
- On verification failure, router sends back to matching with excluded shelters
- Max 2 matching attempts total, never unbounded

### Surplus Lifecycle (Consume-on-Match)

- Full allocation → `status="allocated"` (meal_count preserved)
- Partial allocation → `meal_count -= total`, status stays `"available"`
- GET `/surplus` hides consumed lots by default; `include_all=true` shows them
- POST `/match` returns 409 for consumed/in-flight lots
- Concurrency guard: single in-flight match per lot (set-based, no asyncio.Lock)

### Demo Reset

`POST /api/foodbridge/demo/reset` reseeds demo data, clears claims and event bus.

## Boundaries

### Always Do

- Run `pytest tests/ -q` before committing (backend)
- Run `npm run lint` before committing (frontend)
- Use existing UI components and patterns
- Add tests for new FoodBridge behavior
- Keep API contract in `docs/api-contract.md` updated

### Ask First

- Database schema changes (not currently using DB, but future-proof)
- Adding new dependencies (especially AI/ML libs)
- Modifying agent workflow or retry logic
- Changes to matching weights or scoring

### Never Do

- Commit secrets or API keys (use `.env`)
- Modify `venv/`, `node_modules/`, `__pycache__/`, `.pytest_cache/`
- Hardcode matching numbers (all computed by scoring engine)
- Remove or weaken TypeScript/Python type hints
- Break existing API contract without updating docs

## Testing

### Backend

- `backend/tests/test_foodbridge.py` - 45 tests covering FoodBridge
- `backend/tests/test_openapi_contract.py` - 6 contract tests
- Run with `pytest tests/ -q` (expects 51 passing)
- Tests use `fastapi.testclient.TestClient` and `asyncio.run()`

### Frontend

- `frontend/src/pages/FoodBridge.test.jsx` - Component tests
- Run with `npm run test` (Vitest)

## Common Tasks

### Adding a new FoodBridge endpoint

1. Add route in `backend/app/api/routes_foodbridge.py`
2. Update `docs/api-contract.md`
3. Add test in `backend/tests/test_foodbridge.py`
4. Run tests to verify

### Adding a new agent

1. Add node function in `backend/app/foodbridge/agents.py`
2. Add router if conditional edges needed
3. Register in `backend/app/foodbridge/workflow.py`
4. Add test verifying agent execution

### Modifying matching weights

1. Update defaults in `backend/app/core/config.py`
2. Update `.env.example`
3. Update `docs/foodbridge.md` weights table
4. Run regression test `test_computed_demo_allocation_regression`

### Adding a frontend page

1. Create component in `frontend/src/pages/`
2. Add route in `frontend/src/App.jsx`
3. Use `src/services/api.js` for data fetching

## Environment Setup

### Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev

# Or use DevContainer (VS Code): "Reopen in Container"
```

### Docker

```bash
docker compose up -d --build
# Backend: localhost:8000
# Frontend: localhost:5173 (if configured)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `backend/app/foodbridge/agents.py` | 6 agents + terminals |
| `backend/app/foodbridge/workflow.py` | LangGraph + fallback |
| `backend/app/foodbridge/store.py` | In-memory store + lifecycle |
| `backend/app/foodbridge/scoring.py` | Pure matching math |
| `backend/app/api/routes_foodbridge.py` | HTTP endpoints |
| `backend/app/core/config.py` | All settings |
| `backend/tests/test_foodbridge.py` | 45 FoodBridge tests |
| `docs/foodbridge.md` | Architecture docs |
| `docs/api-contract.md` | API contract |
| `frontend/src/services/api.js` | API client |
| `Makefile` / `demo.ps1` | Demo automation |