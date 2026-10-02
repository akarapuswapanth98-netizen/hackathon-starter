# Hackathon Starter - 24H AI/ML Toolkit

Production-quality, lightweight starter that adapts in hours after problem reveal. Built for 2-person teams.

## 1. Project Overview

- **Frontend**: React 18.3 + Vite 5.4 + `fetch` centralized client (`frontend/src/services/api.js`)
- **Backend**: Python 3.13 + FastAPI 0.141 + Pydantic 2.13 + Uvicorn 0.54
- **AI**: Provider-agnostic LLMService (openai/groq/gemini/anthropic/mock, timeout 30s + 2 retries), LangGraph agent loop (planner -> executor/tools -> validator -> responder, max 5 steps), keyword RAG (honest, no vector DB)
- **Optional**: Supabase/Postgres, scikit-learn, HuggingFace, OpenCV - all disabled by default, app runs with `React + FastAPI + mock LLM` offline.

Preserves existing code - inspect before changing (see `docs/architecture.md`).

## 2. Architecture

See `docs/architecture.md` (Mermaid diagram). Flow: `React -> api.js -> FastAPI /api/* -> Agent (planner/executor+tools/validator/responder) or direct LLM -> Response -> React`.
Endpoints: `GET /api/health`, `POST /api/chat`, `POST /api/solve` (returns `steps[]` trace + `total_duration_ms` + `token_estimate`), `POST /api/solve/stream` (SSE), `POST /api/upload`.
Agent pattern + adding a tool: see `AGENTS.md` + `scripts/new_feature.md` + `backend/app/agents/tools.py`.

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
- `LLM_MODEL=openai/gpt-oss-20b`
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
python -m pytest -q
# 34 passed: 28 in tests/ (api, workflow, agents incl. SSE + RAG, rate-limit, intake) + maps/ml; mock mode, offline

cd frontend
npm run test   # 14 passed (api, Home, ResponseArea)
npm run build  # verifies vite
npm run lint
```

All tests run without API keys (mock provider).

## 8. LLM Configuration

Single abstraction: `backend/app/ai/llm_service.py` (timeout 30s, 2 retries, token estimates, mock offline).
```bash
LLM_PROVIDER=groq
LLM_MODEL=openai/gpt-oss-20b
GROQ_API_KEY=gsk_...
```
Verified live 2026-10-02: `openai/gpt-oss-20b` (fast, JSON-reliable). `llama-3.3-70b-versatile` is Enterprise-only on Groq — not on free keys. Bigger alt: `openai/gpt-oss-120b` (slower, weaker JSON here — see QA notes).
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
- `RAG disabled` 400 -> set `RAG_ENABLED=true` (then restart server — settings load at import)
- CORS error -> check `CORS_ORIGINS` includes frontend URL (default covers `:5173`,`:3000`)
- Timeout 30s -> backend `API_TIMEOUT`, frontend `api.js` TIMEOUT
- `No module named 'app'` -> run from `backend/` or set `PYTHONPATH=backend`
- Port in use (`8000`/`5173`) -> stop other app or `uvicorn app.main:app --port 8001` / `vite --port 5174`
- Windows `npm.ps1 cannot be loaded` -> use `npm.cmd run dev` (execution policy blocks `.ps1`)
- `Makefile` fails on Windows -> use `demo.ps1` / `npm.cmd` instead (Makefile targets assume bash)
- Changed `.env` but nothing happened -> restart uvicorn (settings snapshot at import, no hot-reload for env)
- SSE stalls behind proxy -> server sends `X-Accel-Buffering: no`; for LAN demo prefer direct `http://<host>:8000`, not a buffering proxy
- Large PDF upload slow/fails -> keep uploads <5MB; only first 5 chunks ingested; needs `pypdf` (`pip install pypdf`) or you get `rag_error`
- `429 Rate limited` -> many people share one IP; raise `RATE_LIMIT_PER_MIN` (default 600, `0` disables) and restart
- First `/api/solve` slow -> LangGraph compiles on first call; run `python scripts/preflight.py` to warm up
- Run preflight first: `python scripts/preflight.py` (or `powershell -File scripts/preflight.ps1`)

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

See `docs/api-contract.md`: `GET /api/health`, `POST /api/chat`, `POST /api/solve` (+ `steps` trace), `POST /api/solve/stream` (SSE), `POST /api/upload`, `POST /api/intake` (problem -> ProjectSpec). Central client `frontend/src/services/api.js`.

## Problem Intake (paste statement -> spec + plan)

```bash
# Endpoint (mock works offline, Groq when configured)
curl -X POST http://localhost:8000/api/intake \
  -H "Content-Type: application/json" \
  -d '{"problem":"Patients in rural clinics cannot easily find specialists."}'

# Scaffolder: writes docs/PROJECT_SPEC.md + docs/BUILD_PLAN.md (never app code)
python backend/scripts/scaffold.py "Paste problem statement here"
python backend/scripts/scaffold.py --file problem.txt [--force]
```

## Tests & Build Results

- Backend: `pytest -q 34 passed` (api, workflow, agents/tools/SSE/RAG, rate-limit, intake, maps/ml; mock offline)
- Frontend: `vitest 14 passed`, `vite build ✓ 37 modules`, `eslint pass`

## Still Need Manual Config

- Set `LLM_API_KEY` for real inference (Groq free: `groq.com`, Gemini free: `aistudio.google.com`)
- If RAG needed, set `RAG_ENABLED=true` and `pip install` optional rag deps
- If DB needed, set `SUPABASE_*` and run `database/schema.sql`
- Nothing else mandatory - mock runs demo.

## Files Created (abridged)

`frontend/src/services/api.js`, `pages/Home.jsx`, `components/*`, `vite.config.js`, `backend/app/ai/providers/*`, `agents/state/nodes/workflow`, `rag/*`, `ml/*`, `vision/*`, `database/*`, `evaluation/*`, `api/routes_*.py`, `main.py`, `tests/*`, `docs/*`, `database/schema.sql`, `docker-compose.yml` - see verification below.
