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

## FoodBridge (`tags=["foodbridge"]`) - see docs/foodbridge.md

### GET /api/foodbridge/restaurants
Response: `{"restaurants":[{"id":"rest-001","name":"Green Leaf Restaurant","lat":17.42,"lon":78.48,...}]}`

### GET /api/foodbridge/shelters
Response: `{"shelters":[{"id":"shelter-a","capacity":60,"current_occupancy":10,"urgency":"high","food_requirements":["vegetarian"],...}]}`

### GET /api/foodbridge/surplus
Query: `restaurant_id` (optional). Response: `{"surplus":[{...lot}]}`

### POST /api/foodbridge/surplus  → 201
Request: `{"restaurant_id":"rest-001","meal_count":80,"food_type":"cooked_meals","dietary_tags":["vegetarian"],"expires_in_hours":5,"notes":"..."}`
Response: `{"success":true,"surplus":{...}}`
Errors: unknown restaurant 404, malformed body 422.

### POST /api/foodbridge/match
Request: `{"surplus_id":"food-001","requested_radius_km":10}`
Optional: `shelter_ids`, `options.max_shelters`, `options.include_summary`.
Response (200 always for logical outcomes):
```json
{"success":true,"workflow_id":"...","workflow_status":"completed",
 "allocation":[{"shelter_id":"shelter-a","shelter_name":"...","meals":50,"distance_km":2.11,"score":0.8516,"breakdown":{}}],
 "agent_events":[{"workflow_id":"...","agent":"coordinator","status":"running","detail":"...","timestamp":"..."}],
 "total_allocated":80,"unallocated":0,"summary":"[DEMO MODE] ...","summary_source":"deterministic",
 "retry_count":0,"metadata":{"weights":{},"demo_mode":true,"logistics":{},"duration_ms":0},"error":null}
```
- Unknown `surplus_id`/`shelter_ids`/restaurant → **404** `{error, detail, path}`
- Malformed body → **422**
- Logical failures (expired lot, no candidates, verification exhausted) → **200** with
  `success:false`, `workflow_status:"failed"`, `error:{code,message,details}` (e.g. `VERIFICATION_FAILED`, `SURPLUS_EXPIRED`)
- Timeout → `workflow_status:"timeout"`, `error.code:"MATCH_TIMEOUT"`
- Computed demo output (not hard-coded): `shelter-a:50, shelter-b:30, shelter-c:0`, total 80

### GET /api/foodbridge/agents/events
Query: `workflow_id`, `agent`, `limit` (all optional). Response: `{"events":[{workflow_id,agent,status,detail,timestamp}]}`
