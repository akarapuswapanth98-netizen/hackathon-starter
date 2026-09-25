# Hackathon Starter - 24H AI/ML Toolkit

Production-quality, lightweight starter that adapts in hours after problem reveal. Built for 2-person teams.

## 1. Project Overview

- **Frontend**: React 18 + Vite 5 + `fetch` centralized client
- **Backend**: Python 3.13 + FastAPI 0.115 + Pydantic 2
- **AI**: Provider-agnostic LLMService (openai/groq/gemini/anthropic/mock), LangGraph optional agent workflow, LlamaIndex optional RAG
- **Optional**: Supabase/Postgres, scikit-learn, HuggingFace, OpenCV - all disabled by default, app runs with `React + FastAPI + one LLM`.

Preserves existing code - inspect before changing (see `docs/architecture.md`).

## 2. Architecture

See `docs/architecture.md` (Mermaid diagram). Flow: `React -> api.js -> FastAPI /api/* -> Orchestrator (LLM/LangGraph/RAG/ML/Vision) -> Validator -> Response -> React`.

## 3. Installation

**Backend**:
```bash
cd hackathon-starter/backend
python -m pip install -r requirements.txt
# langgraph etc. optional - minimal base works with mock
```

**Frontend**:
```bash
cd hackathon-starter/frontend
npm.cmd install
```

Check versions before installing (Node 24, Python 3.13 verified).

## 4. Environment Variables

Copy examples:
```bash
copy .env.example backend\.env
copy frontend\.env.example frontend\.env
```

Backend `.env` keys (see `backend/.env.example`):

- `LLM_PROVIDER=mock|openai|groq|gemini|anthropic` (default mock)
- `LLM_MODEL=gpt-4o-mini`
- `LLM_API_KEY` or provider-specific `OPENAI_API_KEY` etc. - never hard-code
- `RAG_ENABLED=false` (set true to enable LlamaIndex)
- `SUPABASE_ENABLED=false`, `SUPABASE_URL`, `SUPABASE_KEY`
- `CORS_ORIGINS=http://localhost:5173,http://localhost:3000`
- `VITE_API_URL=http://localhost:8000` (frontend)

Never expose secrets to frontend.

## 5. Running Frontend

```bash
cd frontend
npm run dev   # http://localhost:5173
npm run build # production
npm run preview
```

Proxy `/api` -> `http://localhost:8000` via `vite.config.js`.

## 6. Running Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
# or
python -m uvicorn app.main:app --reload
```

Health: `http://localhost:8000/api/health` -> `{status:ok, llm_provider, rag_enabled...}` Docs: `/docs`.

## 7. Testing

```bash
cd backend
python -m pytest tests/ -v
# 16 tests: health, validation, workflow, failure handling

cd frontend
npm run build  # verifies vite
# frontend tests: vitest (if added)
```

All tests run without API keys (mock provider).

## 8. LLM Configuration

Single abstraction: `backend/app/ai/llm_service.py` (also `app/services/llm_service.py` alias).
```bash
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=gsk_...
```
Change env only - no code rewrite. Adapters isolated in `backend/app/ai/providers/*.py`. Missing key -> 503 with `LLM provider 'x' not configured` (no stack leak).

## 9. RAG Activation

Disabled by default. To enable:

```bash
# backend/.env
RAG_ENABLED=true
# optional
RAG_PROVIDER=mock
```
Install only if needed: `pip install llama-index pypdf sentence-transformers`
Use: `POST /api/upload` PDF -> ingest -> `POST /api/solve {query, use_rag:true}` -> sources returned. See `docs/customization-guide.md C`.

## 10. Database Activation

Disabled by default. To enable Supabase:
```bash
SUPABASE_ENABLED=true
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=ey...
pip install supabase
```
Schema: `database/schema.sql`. App still runs if disabled (mock saves).

## 11. ML Activation

Templates in `backend/app/ml/`:

- `preprocessing.py` -> clean, split
- `classifier.py` -> RandomForestClassifier
- `predictor.py` -> RandomForestRegressor + predict_single

Install when needed: `pip install scikit-learn pandas`. No fake training.

## 12. Vision Activation

`backend/app/vision/service.py` - lazy. Check `cv2`/`transformers` availability. For hackathon:

```bash
pip install opencv-python ultralytics Pillow transformers
```

Upload image via `POST /api/upload` -> vision analysis.

## 13. Demo Mode

Clearly labeled. Mock provider (`LLM_PROVIDER=mock`) returns `[MOCK model] ... Mock - set LLM_API_KEY` with same workflow. Frontend shows yellow `DEMO MODE` banner in `ResponseArea.jsx`. Real path remains available - just set env key.

## 14. Deployment

**Backend** (Render/Fly): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
**Frontend** (Vercel): `npm run build` -> `dist/` ; set `VITE_API_URL` to backend URL.
**Docker** (optional): `docker-compose up` - only if needed, lightweight.

## 15. Troubleshooting

- `LLM provider not configured` -> set `LLM_API_KEY` or provider-specific key in `backend/.env`
- `RAG disabled` 400 -> set `RAG_ENABLED=true`
- CORS error -> check `CORS_ORIGINS` includes frontend URL
- Timeout 30s -> backend `API_TIMEOUT`, frontend `api.js` TIMEOUT
- `No module named 'app'` -> run from `backend/` or set `PYTHONPATH=backend`

## 16. Hackathon Customization Guide

See `docs/customization-guide.md` and `docs/architecture.md`.

### 24-HOUR HACKATHON MODE

1. Read problem, identify input/users/output/AI/data/constraints.
2. Choose architecture: Simple LLM | Agent | RAG | ML | Vision | Hybrid.
3. Remove unnecessary modules.
4. Implement core: prompts (`ai/prompts.py`), nodes (`agents/nodes.py`), or ml/vision.
5. Test with `examples/sample-inputs`.
6. Polish `frontend/src/pages/Home.jsx`.
7. Demo via `docs/demo-plan.md` (3 min: 20+20+70+30+25+15).
8. Presentation via `docs/presentation-outline.md`.
9. Final E2E `python -m pytest` + `npm run build`.

Per-type: A. Normal LLM -> `prompts.py`, `use_agents=false` | B. Agentic -> `nodes.py`+`workflow.py` | C. RAG -> enable + upload | D. ML -> `ml/` + CSV | E. Vision -> `vision/service.py` | F. Data -> `ml/preprocessing` + `evaluation`.

Two-person: P1 Lead/AI-Backend (architecture, FastAPI, LLM, LangGraph, RAG, ML, DB) + P2 Frontend/Product (React, api.js, testing, demo flow, docs, presentation) sharing `POST /api/solve` contract.

## API Contract

See `docs/api-contract.md`: `GET /api/health`, `POST /api/chat`, `POST /api/solve`, `POST /api/upload`. Central client `frontend/src/services/api.js`.

## Tests & Build Results

- Backend: `pytest tests/ 16 passed` (health, validation, workflow, RAG disabled, upload)
- Frontend: `vite build ✓ 36 modules, 152kB (gzip 49kB)`

## Still Need Manual Config

- Set `LLM_API_KEY` for real inference (Groq free: `groq.com`, Gemini free: `aistudio.google.com`)
- If RAG needed, set `RAG_ENABLED=true` and `pip install` optional rag deps
- If DB needed, set `SUPABASE_*` and run `database/schema.sql`
- Nothing else mandatory - mock runs demo.

## Files Created (abridged)

`frontend/src/services/api.js`, `pages/Home.jsx`, `components/*`, `vite.config.js`, `backend/app/ai/providers/*`, `agents/state/nodes/workflow`, `rag/*`, `ml/*`, `vision/*`, `database/*`, `evaluation/*`, `api/routes_*.py`, `main.py`, `tests/*`, `docs/*`, `database/schema.sql`, `docker-compose.yml` - see verification below.
