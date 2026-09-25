# Hackathon Customization Guide

## 24-HOUR MODE

**Step 1** Read problem statement.

**Step 2** Identify: input, users, required output, AI requirement, data, constraints.

**Step 3** Choose architecture:
- Simple LLM -> chat/solve direct
- Agent -> LangGraph workflow
- RAG -> enable RAG
- ML -> ml/*
- Vision -> vision/*
- Hybrid -> combine

**Step 4** Remove unnecessary modules (delete imports, keep lightweight).

**Step 5** Implement core solution (see per-type below).

**Step 6** Test with realistic examples (examples/sample-inputs).

**Step 7** Polish UI (Home.jsx).

**Step 8** Demo (docs/demo-plan.md).

**Step 9** Presentation (docs/presentation-outline.md).

**Step 10** Final E2E test.

---

## A. Normal LLM Application

Files: `backend/app/api/routes_chat.py`, `backend/app/ai/prompts.py`
- Change `SYSTEM_REASONER` in `prompts.py`
- Keep `use_agents=false` in frontend for direct LLM
- No RAG/ML/Vision needed

## B. Agentic Workflow

Files: `backend/app/agents/nodes.py`, `workflow.py`, `state.py`
- Add nodes: `researcher`, `calculator`, `tool` in `nodes.py`
- Wire in `workflow.py`: `workflow.add_node("researcher", fn)` + `add_edge`
- Extend `AgentState` in `state.py` with new fields
- Keep retry limits <3

## C. RAG / Document

Files: `backend/app/rag/*`, `backend/app/api/routes_upload.py`, `frontend/src/components/FileUpload.jsx`
- Set `RAG_ENABLED=true` in `backend/.env`
- `pip install llama-index pypdf sentence-transformers`
- Ingest: `POST /api/upload` PDF -> `rag/service.py ingest_text`
- Query: `POST /api/solve {query, use_rag:true}` -> retrieve + LLM

## D. ML Prediction

Files: `backend/app/ml/*`, `backend/app/api/routes_upload.py`
- `pip install scikit-learn pandas`
- Upload CSV via `FileUpload`
- In solve handler: `df = pd.read_csv(path); train_classifier(df, target)`
- Return `accuracy` + allow `predict_single`

## E. Computer Vision

Files: `backend/app/vision/service.py`, `frontend FileUpload`
- `pip install opencv-python ultralytics Pillow`
- Upload image via `/api/upload` (vision branch)
- `vision/service.py analyze_image` -> YOLO `model.predict`
- Add LLM explain: `providers/gemini.py` vision variant

## F. Data Analysis

- Use `ml/preprocessing.py` + `evaluation/metrics.py`
- Add `database/service.py` if persistence needed (SUPABASE_ENABLED=true)

---

## Which Files to Change - Cheat Sheet

| Need | Change |
|------|--------|
| Prompt | `backend/app/ai/prompts.py` |
| LLM provider | `.env LLM_PROVIDER/LM_API_KEY` |
| Add agent step | `agents/nodes.py` + `workflow.py` |
| RAG | `rag/service.py` + `RAG_ENABLED` |
| ML | `ml/*.py` |
| Vision | `vision/service.py` |
| DB | `database/service.py` + `SUPABASE_ENABLED` |
| UI | `frontend/src/pages/Home.jsx` |
| API URL | `frontend/.env VITE_API_URL` |
| Upload | `api/routes_upload.py` |

Two-person split: **Person 1 (AI/Backend)**: FastAPI, LLM, LangGraph, RAG/ML/DB | **Person 2 (Frontend/Product)**: React, API integration, demo, docs, presentation
