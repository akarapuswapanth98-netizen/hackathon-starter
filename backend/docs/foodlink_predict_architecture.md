# FoodLink Predict — backend architecture

Built **on top of** Hackathon Starter Toolkit V4. This document is the map: what
was reused, what was added, and why the boundary sits where it does.

---

## 1. Division of responsibility

| System | Role |
|---|---|
| **FoodLink Predict** | The **early intelligence producer.** Forecasts demand, scores waste risk, ranks recovery actions, explains them, publishes a *forecast* surplus listing. |
| **FoodLink** | The **redistribution executor.** Its six agents (detect, match, negotiate, hand off, deliver, verify) run in the FoodLink system. |

Predict never executes a rescue. It produces an early, evidence-backed signal
that FoodLink can act on before the food is at risk. The two meet at exactly one
place: `adapters/`.

---

## 2. What the existing V4 provided, and what it didn't

An audit of `hackathon-starter/backend` established the following **before** any
code was written. It is included because it explains several design choices.

**Present and reused as-is**

| Concern | Module | How FLP uses it |
|---|---|---|
| App factory | `app/main.py` | 4 additive lines: import + `include_router`, feature-flagged and guarded |
| Settings | `app/core/config.py` `Settings` | ~14 new env fields appended to the same class |
| Errors | `app/core/errors.py` `AppError` + handlers | every FLP error subclasses it, so responses match the starter's shape |
| LLM | `app/ai/llm_service.py` `LLMService` | mock provider offline; real providers by env var |
| Agents | `app/agents/nodes.py`, `workflow.py` `MAX_STEPS` | same planner→tools→executor→validator→responder shape |
| Tool registry | `app/agents/tools.py` `@register_tool` | all 6 FLP tools registered into the shared `TOOL_REGISTRY` |
| JSON repair | `app/agents/nodes.py::_extract_json_object` | reused for the agent's structured selection |
| Maps | `app/maps/provider.py` `get_provider().haversine_km` | inter-site transfer distance (see §7 caveat) |
| ML | `app/ml/templates.py`, `app/ml/predictor.py` | same optional-deps philosophy: lazy import, `ML_ENABLED`-style gating |
| Auth | `app/auth/jwt.py` | `AUTH_ENABLED` + an `org_id` claim for tenancy |
| SSE | `app/api/routes_solve.py::solve_stream` | same `StreamingResponse` + `data: {json}\n\n` convention |
| Docs/scaffold | `docs/`, `scripts/scaffold.py` | followed |

**Did NOT exist.** The PDF assumed these; none were present, so FLP owns them
rather than modifying the toolkit:

* `/api/upload` accepting domain CSVs → FLP adds `/api/ingest`; `/api/upload`
  is untouched and still works for RAG documents.
* `ml/predictor.py` quantile forecasting → `projects/foodlink_predict/forecast.py`.
* `ml/preprocessing.py` domain features → `projects/foodlink_predict/features.py`.
* `agents/tools.py` domain tools → registered **into** that same module.
* A validator module → `projects/foodlink_predict/validators.py`.
* `database/schema.sql` tables → appended (existing tables untouched).
* Any persistence → `projects/foodlink_predict/db.py` (own SQLite file).

**Two toolkits exist on this machine.** `hackathon-starter` (a git repo) is the
real V4 and matches the PDF on every referenced path. `hackathon-toolkit-v4` is a
smaller unrelated scaffold with no upload/solve/SSE and no FoodLink integration;
it was not used.

---

## 3. Layer map

```
HTTP  routes.py ──────────────► demo/routes.py
        │                              │
        ▼                              ▼
   service.py  ──► surplus.py ──► adapters/  (the ONLY FoodLink seam)
        │              │
        ▼              ▼
     agent.py      validators.py  (hard gate, no LLM path)
     tools.py ──────► deterministic pipeline:
        │              ingest → features → forecast → risk → actions
        ▼
   db.py / models.py        (own Base metadata; org-scoped queries only)
        │
   app.core / app.ai / app.agents / app.maps  (reused V4 modules)
```

Import rule (enforced by convention and reviewed): the toolkit never imports a
project; a project may import the toolkit freely.

---

## 4. Data model

Eleven tables, all prefixed `flp_`, all created from their own `FLPBase`
metadata so `create_all` can never touch a starter table.

`flp_organizations`, `flp_locations`, `flp_items`, `flp_batches`,
`flp_sales_daily`, `flp_calendar_days`, `flp_forecasts`, `flp_waste_risk`,
`flp_recommendations`, `flp_surplus_listings`, `flp_impact_events`
(+ `flp_runs` for observability).

**Multi-tenancy.** Every tenant-owned table is keyed on `(org_id, id)`. An
earlier iteration keyed on `id` alone, which meant two organizations could not
both own a location called `loc_main_canteen` — a real bug, caught by the
security tests and fixed. Queries go through `db.py` helpers that always take
`org_id`; there are no ORM relationships between tenant-scoped tables, because a
single-column foreign key against a composite parent would be wrong.

Postgres/Supabase DDL and an RLS policy template are appended to
`database/schema.sql`.

---

## 5. Deterministic pipeline

`ingest → features → forecast → risk → actions` contains **no LLM call at all**.
Every number the system acts on is produced there and stored, so any number in a
recommendation can be traced to a row.

* **Ingest** — header-alias detection, per-row validation with issue codes
  (`unknown_item`, `negative_quantity`, `invalid_date`, `missing_columns`, …),
  natural-key upserts, and a `source` column that distinguishes `synthetic` from
  `uploaded`.
* **Forecast** — P10/P50/P90 per ITEM × LOCATION × DAY, three quantile heads,
  chronological-holdout calibration, mandatory seasonal-naive baseline.
* **Risk** — `expected_unsold`, `risk`, `urgency_hours`, `donate_by`, `priority`.
* **Actions** — the recovery ladder, evaluated *sequentially over quantity* so
  the plan reads "transfer 110, donate the remaining 129".

---

## 6. Where the LLM sits

```
risk + ladder (deterministic)
        │
        ▼
   PLANNER ──► TOOLS (deterministic; never LLM-routed)
        │
        ▼
   EXECUTOR ──► LLM may: pick one allowed action, write prose
        │      LLM may NOT: emit a quantity, date, score, or deadline
        ▼
   VALIDATOR ──► hard gates; a failure forces a replan
        │
        ▼
   RESPONDER ──► rationale + structured action
```

The agent's selection is constrained twice: the ladder marks what is *allowed*,
and `proposal_for_step` overwrites `action`/`quantity`/`deadline` from the
deterministic plan *after* the LLM has spoken. A second gate,
`can_publish_listing`, re-checks the live clock at the adapter boundary so a
stale approval cannot be redeemed into a live listing.

---

## 7. Transfer ETA — a known approximation

The starter's `MapsProvider` exposes `haversine_km` and nothing else: no
routing, no traffic, no ETA. FLP therefore computes
`eta = distance / transport_kmh`, with the speed in `ActionRule.transport_kmh`
(configurable, not a constant), and labels every ETA `haversine+estimated`.
Locations with no coordinates return *infeasible* rather than a fabricated
number. A live routing provider would replace `_eta()` in `actions.py` and
nothing else.

---

## 8. Observability

* `X-Request-ID` comes from the toolkit middleware.
* Structured logging via `logging.getLogger("flp.*")`.
* `flp_runs` records stage, model version, duration, tool calls and outcome —
  metadata only. Prompts and credentials are never written.
* `scripts/check_secrets.py`-style discipline: no secret is read by FLP except
  `FOODLINK_API_KEY`, which is read in `adapters/factory.py`, passed to the
  adapter and logged only via `util.redact()` (last 4 characters).

---

## 9. Offline demo

`POST /api/demo/scenario` runs the whole story in one call with no network, no
keys and no database server. It is deterministic for a fixed `as_of` and `seed`.
Every step reports what actually happened; a validator refusal is reported as a
refusal rather than hidden to keep the narrative tidy.

See `docs/foodlink_predict_demo.md` for the expected output.