# API Contract

Base: `http://localhost:8000` (or `VITE_API_URL`)

## GET /api/health

Response:
```json
{"status":"ok","version":"0.1.0","llm_provider":"mock","llm_model":"gpt-4o-mini","rag_enabled":false,"db_enabled":false,"llm_configured":true}
```

## POST /api/chat

Request:
```json
{"message":"Hello","use_rag":false,"conversation_id":null,"metadata":{}}
```
Response:
```json
{"reply":"...","provider":"mock","model":"gpt-4o-mini","sources":[],"meta":{}}
```
Error if RAG enabled but disabled: 400 `RAG disabled`

## POST /api/solve

Request (spec):
```json
{"query":"problem","context":"extra","use_rag":false,"use_agents":true,"options":{}}
```
Alias: `{"problem":"..."}` also accepted.
Response:
```json
{"success":true,"answer":"...","sources":[],"metadata":{"workflow":"langgraph"},"confidence":null,"reasoning_steps":["planner..."]}
```
`confidence` is null unless calculated (don't fake).

## POST /api/upload

Form: `file` (txt, md, csv, pdf, jpg, png)
Response:
```json
{"filename":"a.pdf","saved_as":"<uuid>.pdf","size":1234,"ext":".pdf","rag_ingested":2}
```
- Text/PDF + RAG_ENABLED => ingest chunks
- Image => vision analysis

## Frontend Client

Single file: `frontend/src/services/api.js`
- `api.health()`, `api.chat(payload)`, `api.solve(payload)`, `api.upload(file)`
- Timeout 30s, JSON error handling, base URL from `VITE_API_URL`

Errors: `{error, detail, path}` never leak secrets. Validation 422, missing key 503, RAG disabled 400.
