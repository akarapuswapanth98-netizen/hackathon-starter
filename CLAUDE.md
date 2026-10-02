# CLAUDE.md

> Quick reference for AI assistants working on hackathon-starter

## Project Overview

**hackathon-starter** is a full-stack Python/React monorepo for rapid hackathon development. FastAPI backend with LangGraph agent workflow + Vite/React frontend.

For detailed guidelines, see [AGENTS.md](AGENTS.md).

## Quick Commands

```bash
# Backend
cd backend
python -m pytest tests/ -q              # Run tests
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
| `backend/app/agents/workflow.py` | LangGraph agent loop + fallback |
| `backend/app/agents/tools.py` | Tool registry |
| `backend/app/ai/llm_service.py` | Provider-agnostic LLM |
| `backend/app/api/routes_chat.py` | Chat endpoint |
| `backend/app/api/routes_solve.py` | Solve + agents + SSE |
| `backend/app/api/routes_upload.py` | File upload + RAG ingest |
| `backend/app/core/config.py` | All settings |
| `backend/tests/test_api.py` | API tests |
| `docs/api-contract.md` | API contract |
| `frontend/src/services/api.js` | API client |

## Endpoints

```
GET  /api/health
POST /api/chat
POST /api/solve              # use_agents=true runs agent graph, returns steps
POST /api/solve/stream       # SSE agent steps
POST /api/upload             # file + RAG ingest
```

## Code Patterns

### Python
- Type hints everywhere
- Pure functions for agents, TypedDict state
- Pydantic v2 for all API schemas

### React
- Single API client in `src/services/api.js`
- Page-level data fetching
- ESLint

## Before Committing

1. Backend: `cd backend && python -m pytest tests/ -q`
2. Frontend: `cd frontend && npm run lint`
3. Never commit secrets (use `.env`)

## Environment

Backend `.env`:
```bash
LLM_PROVIDER=mock          # mock | openai | groq | anthropic | gemini
LLM_API_KEY=               # Required for real providers
RAG_ENABLED=false
AUTH_ENABLED=false
```

## Demo Flow

```bash
# 1. Start backend
cd backend && uvicorn app.main:app --port 8000

# 2. Chat
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello"}'

# 3. Solve with agents
curl -X POST http://localhost:8000/api/solve \
  -H "Content-Type: application/json" \
  -d '{"query":"Summarize RAG impact","use_agents":true}'
```
