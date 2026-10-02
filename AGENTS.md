# AGENTS.md

> Guidelines for AI coding agents working on this project.

## Project Overview

**hackathon-starter** is a full-stack Python/React monorepo for rapid hackathon development. FastAPI backend with LangGraph agent workflow and Vite/React frontend.

### Tech Stack

- **Backend:** Python 3.13, FastAPI 0.141, LangGraph 1.2, Pydantic 2.13, Uvicorn 0.54
- **Frontend:** React 18.3, Vite 5.4, ESLint 8.57
- **Database:** SQLite fallback / PostgreSQL-ready, Supabase optional
- **AI/ML:** LangChain Core 1.6, LangGraph, configurable LLM providers (OpenAI, Groq, Anthropic, Gemini, mock)
- **Testing:** pytest 9.1 (backend), Vitest 1.6 (frontend)

## Project Structure

```
/
├── backend/
│   ├── app/
│   │   ├── api/               # routes_health, routes_chat, routes_solve, routes_upload, routes_auth
│   │   ├── core/              # config, errors
│   │   ├── ai/                # LLMService + providers/
│   │   ├── agents/            # state, nodes, workflow, tools
│   │   ├── rag/               # keyword retrieval + ingest
│   │   ├── database/          # service (mock/SQLite)
│   │   ├── auth/              # JWT (optional, OFF by default)
│   │   ├── maps/              # haversine provider
│   │   ├── ml/                # sklearn templates
│   │   └── vision/            # stub templates
│   ├── tests/                 # test_api, test_workflow
│   ├── requirements.txt       # single source of truth
│   └── pyproject.toml         # synced to requirements
├── frontend/
│   ├── src/pages/Home.jsx
│   ├── src/services/api.js    # health/chat/solve/upload only
│   └── vite.config.ts
├── docs/
├── examples/sample-inputs/
├── Makefile / demo.ps1 / demo.sh
├── docker-compose.yml
├── AGENTS.md / CLAUDE.md / README.md
```

## Commands

```bash
# Backend
cd backend
python -m pip install -r requirements.txt
python -m pytest tests/ -q
uvicorn app.main:app --port 8000

# Frontend
cd frontend
npm install
npm run dev
npm run build
npm run lint
npm run test
```

## Code Style

- Python: type hints, `snake_case` funcs, `PascalCase` classes, Pydantic v2 schemas.
- React: `camelCase` funcs, `PascalCase` components, single API client.

## Configuration (`.env`, never commit)

```bash
LLM_PROVIDER=mock
LLM_API_KEY=
LLM_MODEL=openai/gpt-oss-20b
RAG_ENABLED=false
AUTH_ENABLED=false
JWT_SECRET=
API_TIMEOUT=30
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
VITE_API_URL=http://localhost:8000
```

Auth is OFF by default. If `AUTH_ENABLED=true` without `JWT_SECRET`, the app refuses to start.

## Agent Pattern

See `backend/app/agents/`: `state.py`, `tools.py` (decorator registry), `workflow.py` (planner->executor loop->validator->responder), `nodes.py`.
`POST /api/solve` with `use_agents=true` returns `steps[]` with node/tool/duration. `POST /api/solve/stream` emits SSE steps.

Adding a tool: define a function + Pydantic args, decorate with `@register_tool`, under 10 lines. See `scripts/new_feature.md`.

## Boundaries

- Run `pytest tests/ -q` + `npm run lint` before committing.
- Never commit secrets, `venv/`, `node_modules/`, `__pycache__/`.
- Do not claim LlamaIndex/vector search; RAG is keyword retrieval.

## Tests

- Backend `python -m pytest -q`: 30 passed (24 in `backend/tests/` incl. agents/SSE/RAG/rate-limit + maps/ml). Mock offline.
- Frontend `npm run test`: 14 passed; `npm run build` + `npm run lint` pass.
