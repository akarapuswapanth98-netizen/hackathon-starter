# FoodBridge AI - Multi-Agent Surplus Food Matching

Matches restaurants' surplus food with nearby shelters in real time using a
multi-agent architecture: six specialized agents negotiate and hand off tasks
autonomously through a LangGraph workflow with bounded verification retry.

## Architecture

```
backend/app/foodbridge/
  __init__.py     package exports
  models.py       Pydantic models (Restaurant, FoodSurplus, Shelter, MatchRequest/Response)
  state.py        FoodBridgeState (TypedDict threaded through the graph)
  store.py        in-memory store + demo seed (swap for a DB later)
  scoring.py      pure deterministic matching math (no I/O, no LLM)
  events.py       EventStore - agent event bus (survives timeouts)
  prompts.py      coordinator summary prompt + labeled demo/fallback templates
  agents.py       the six agent nodes + terminals + pure routers
  workflow.py     LangGraph StateGraph, sequential fallback, timeout runner
backend/app/api/routes_foodbridge.py   HTTP layer (mounted in main.py, tags=["foodbridge"])
backend/tests/test_foodbridge.py       23 tests
```

Reuses the starter's existing infrastructure: `LLMService` (provider-agnostic),
`AppError` error handling, `Settings` config pattern, event/log conventions.

## The Six Agents

| # | Agent | Responsibility | Failure mode |
|---|-------|----------------|--------------|
| 1 | **coordinator** | Validate request, initialize workflow state | missing surplus/restaurant → error path |
| 2 | **restaurant** | Load surplus lot, compute `hours_remaining` | rejects invalid/expired lots (`SURPLUS_EXPIRED`) |
| 3 | **shelter** | Load/filter candidates: radius, dietary compatibility, usable demand | no candidates → `NO_MATCHING_SHELTERS` |
| 4 | **matching** | Deterministic weighted scores + two-pass greedy allocation; on retry excludes shelters named in `verification.issues` | - |
| 5 | **logistics** | Ordered delivery batches (nearest first), ETA, route distance | - |
| 6 | **verification** | Hard-constraint audit of the allocation; grants bounded retry | exhausted → `VERIFICATION_FAILED` |

Terminal nodes: `coordinator_final_node` (LLM summary) and
`coordinator_error_node` (structured `{code, message, details}`).

Every node emits exactly one structured `AgentEvent`
(`workflow_id, agent, status, detail, timestamp`) into `EventStore`.

## Workflow

```
coordinator ──▶ restaurant ──▶ shelter ──▶ matching ──▶ logistics ──▶ verification
     │              │             │                                    │
   error          error         error                    ┌──────────────┼──────────────┐
     ▼              ▼             ▼                       ▼              │              │
coordinator_error◀──┴─────────────┘              valid: coordinator_final  │        retry (retry_count
                                                                          │         < MATCH_MAX_RETRIES)
                                                                          ▼              │
                                                                   response             matching (2nd attempt)
                                                                                            │
                                                                               exhausted: coordinator_error
```

- Real `langgraph.StateGraph` with `add_conditional_edges` for the four routers
  (`coordinator_router`, `restaurant_router`, `shelter_router`, `verification_router`).
- If langgraph cannot be imported, `_SequentialFoodBridge` runs the identical
  flow sequentially - the backend never breaks on an optional dependency.
- `run_match_workflow()` wraps execution in `asyncio.wait_for` (`MATCH_TIMEOUT_SECONDS`,
  default 10s). On timeout: `workflow_status="timeout"`, events recovered from the bus.

## Matching Algorithm

Pure functions in `scoring.py`. Per-shelter score (weights normalized to sum 1.0):

```
score = w_distance  * (1 - km/10)                # closer is better, floor at 10 km
      + w_demand    * (need / max_need)           # capacity - current_occupancy
      + w_urgency   * (high=1.0, medium=0.6, low=0.3)
      + w_capacity  * (capacity / max_capacity)
      + w_compat    * (food_requirements ⊆ dietary_tags ? 1.0 : fraction)
      + w_expiry    * (1 - travel_hours / hours_to_expiry)   # 25 km/h van speed
```

Distances: haversine. Ranking: score desc, shelter id asc (fully deterministic).

**Two-pass greedy allocation** over the ranked list:
1. **Pass 1 (full fill):** give each shelter its *entire* demand while it fits -
   no shelter starves while another gets a partial share it didn't need.
2. **Pass 2 (partial):** spread leftovers across remaining shelters, capped at
   their demand.

Never exceeds lot size or any shelter's demand. Allocation is **computed, never
hard-coded** - the LLM is never used for numbers.

## Weight Configuration

Configured in `core/config.py` / `.env`, normalized at runtime (sums to 1.0 even
if you set arbitrary values; all-zero → uniform):

| Env var | Default | Meaning |
|---|---|---|
| `MATCH_W_DISTANCE` | **0.50** | proximity dominates (perishable food) |
| `MATCH_W_DEMAND` | 0.10 | shelter need relative to max need |
| `MATCH_W_URGENCY` | 0.15 | high/medium/low urgency |
| `MATCH_W_CAPACITY` | 0.05 | shelter size |
| `MATCH_W_COMPATIBILITY` | 0.10 | dietary fit |
| `MATCH_W_EXPIRY` | 0.10 | can the van arrive before spoilage |
| `MATCH_TIMEOUT_SECONDS` | 10 | workflow timeout |
| `MATCH_MAX_RETRIES` | 1 | bounded verification retries |
| `FOODBRIDGE_DEMO_MODE` | auto | `auto \| true \| false` (see below) |

## Retry Behavior (bounded, never unbounded)

`MATCH_MAX_RETRIES=1` → **at most TWO matching attempts total**.

1. `verification_node` audits: expired lot, unknown shelter, `meals ≤ shelter demand`,
   `total ≤ lot meal_count`, dietary compatibility, non-negative meals.
2. If invalid **and** `retry_count < MATCH_MAX_RETRIES` → grant retry
   (`retry_count += 1`), router sends state back to **matching**.
3. Matching repairs by **excluding the shelters named in `verification.issues`**
   and recomputing scores/allocation.
4. Second failure → router exits to `coordinator_error` with
   `code="VERIFICATION_FAILED"` and the issue list in `details`.

The router derives the next hop from state (`passed` / `grant_retry`) - pure
functions, unit-testable, structurally incapable of looping forever.

## Demo Scenario

Seeded by `store.py` (all values feed the scoring engine):

- **Green Leaf Restaurant** (`rest-001`) at (17.4200, 78.4800)
- Lot **`food-001`**: 80 `cooked_meals`, `dietary_tags=["vegetarian"]`,
  prepared now−1h, expires **now+5h**
- Shelters (all `food_requirements=["vegetarian"]`):

| Shelter | Distance | Demand (cap−occ) | Urgency |
|---|---|---|---|
| shelter-a | ~2.1 km | 50 (60−10) | high |
| shelter-b | ~4.7 km | 30 (40−10) | medium |
| shelter-c | ~3.2 km | 70 (80−10) | high |

### Computed demo allocation (recorded from the running implementation)

```
ranking:  shelter-a 0.8516  >  shelter-c 0.8378  >  shelter-b 0.6178
allocation: shelter-a: 50 meals, shelter-b: 30 meals, shelter-c: 0 meals
total_allocated 80, unallocated 0, retry_count 0, workflow_status "completed"
```

**Why:** with distance at 0.50, C (3.2 km, high urgency) outranks B (4.7 km,
medium) - as the weighting predicts. But allocation is two-pass *full-fill*:
A takes its full 50, leaving 30; C needs 70 which doesn't fit, so the remainder
goes to B whose full demand of 30 fits exactly. C gets 0 not because it ranked
low, but because its demand exceeds the leftover. Change the weights in `.env`
and this split changes accordingly - nothing is hard-coded.
Pinned as a regression test in `test_computed_demo_allocation_regression`.

## Endpoints

All under `/api/foodbridge` (mounted with `tags=["foodbridge"]`):

| Method | Path | Returns |
|---|---|---|
| GET | `/api/foodbridge/restaurants` | `{"restaurants": [...]}` |
| GET | `/api/foodbridge/shelters` | `{"shelters": [...]}` |
| GET | `/api/foodbridge/surplus?restaurant_id=` | `{"surplus": [...]}` |
| POST | `/api/foodbridge/surplus` | **201** `{"success": true, "surplus": {...}}` |
| POST | `/api/foodbridge/match` | 200 `MatchResponse` (see below) |
| GET | `/api/foodbridge/agents/events?workflow_id=&agent=&limit=` | `{"events": [...]}` |

Errors: unknown surplus/shelter/restaurant → **404** `AppError`
(`{error, detail, path}`); malformed body → **422**; logical workflow failures
(expired lot, no candidates, verification exhausted) → **200** with
`workflow_status="failed"` + structured `error` so the frontend can render the
agent trail.

### POST /api/foodbridge/match

Request:
```json
{"surplus_id": "food-001", "requested_radius_km": 10}
```
(`surplus_id` optional → defaults to newest lot; `shelter_ids`, `options.max_shelters`,
`options.include_summary` optional.)

Response:
```json
{
  "success": true,
  "workflow_id": "…",
  "workflow_status": "completed",
  "allocation": [
    {"shelter_id": "shelter-a", "shelter_name": "…", "meals": 50,
     "distance_km": 2.11, "score": 0.8516, "breakdown": {"distance": {"score": 0.7887, "weight": 0.5, "weighted": 0.3944}, "...": "..."}}
  ],
  "agent_events": [{"workflow_id": "…", "agent": "coordinator", "status": "running", "detail": "workflow started", "timestamp": "…"}],
  "total_allocated": 80,
  "unallocated": 0,
  "summary": "[DEMO MODE] Green Leaf Restaurant has 80 surplus meals…",
  "summary_source": "deterministic",
  "retry_count": 0,
  "metadata": {"weights": {"distance": 0.5, "…": 0}, "demo_mode": true, "logistics": {"batches": ["…"]}, "duration_ms": 123.4},
  "error": null
}
```

## Frontend Integration

`frontend/src/services/api.js` is the single fetch layer (do not scatter
fetches). Add these methods next to the existing ones:

```js
// --- FoodBridge ---
listRestaurants: () => request("/foodbridge/restaurants"),
listShelters:    () => request("/foodbridge/shelters"),
listSurplus:     (restaurantId) =>
  request(`/foodbridge/surplus${restaurantId ? `?restaurant_id=${restaurantId}` : ""}`),
createSurplus:   (payload) => request("/foodbridge/surplus", { method: "POST", body: payload }),
matchFood:       (payload) => request("/foodbridge/match", { method: "POST", body: payload }),
agentEvents:     (workflowId) =>
  request(`/foodbridge/agents/events?workflow_id=${workflowId}`),
```

Typical flow:

```js
const result = await api.matchFood({ surplus_id: "food-001", requested_radius_km: 10 });
if (result.success) {
  setAllocation(result.allocation);          // meals per shelter + score breakdown
  setRoute(result.metadata.logistics.batches); // ordered delivery stops + ETA
  renderTimeline(result.agent_events);       // live agent trail
  showToast(result.summary);                 // labeled [DEMO MODE] in demo
} else {
  renderStructuredError(result.error);       // {code, message, details}
}
```

## Run Instructions

```bash
cd backend
pip install -r requirements.txt      # fastapi, langgraph, pytest (no new deps needed)
uvicorn app.main:app --reload        # http://localhost:8000  (docs at /docs)

# smoke test
curl http://localhost:8000/api/foodbridge/shelters
curl -X POST http://localhost:8000/api/foodbridge/match \
     -H "Content-Type: application/json" \
     -d '{"surplus_id":"food-001","requested_radius_km":10}'

# tests (16 starter + 23 foodbridge)
python -m pytest tests/ -q
```

## DEMO_MODE Explained

`FOODBRIDGE_DEMO_MODE = auto | true | false` (default **auto**):

- **auto** (or unset): demo mode is ON when no real LLM API key is configured
  (`LLM_PROVIDER=mock` or empty key) → summary comes from the deterministic
  template labeled **`[DEMO MODE]`**, `summary_source="deterministic"`.
  Set a real provider + key (`LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`) and
  auto flips to OFF → `coordinator_final_node` calls `LLMService` for the
  natural-language summary, `summary_source="llm:openai"`.
- **true**: always deterministic template (stages/cases where you must not spend
  tokens).
- **false**: always attempt the LLM; if it fails, fall back to the template
  labeled `[FALLBACK]` with `summary_source="llm-fallback:..."`.

Rules honored: the LLM only ever writes the prose summary - **never numbers**
(all figures come from the matching engine), and no LLM output is ever
fabricated or presented without its source tag.

## Demo/Rehearsal Only (NOT a production feature)

`POST /api/foodbridge/demo/reset` → `{"success": true, "message": "Demo data reset"}`

Re-seeds the demo store (`rest-001`, 3 shelters, `food-001`/80/`available`),
clears in-flight match claims and the agent event bus — no auth, for live
judge demos only. Lets you re-run the full match on stage without restarting
the server: match (consumes the lot) → 409 on repeat → reset → match succeeds
again. Never expose or rely on this in production.
