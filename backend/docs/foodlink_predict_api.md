# FoodLink Predict — API reference

Base URL: `http://localhost:8000`. All paths are under the starter's `/api`
prefix, which `API_PREFIX` controls.

**Responses.** Success: `{"success": true, "data": {...}, "meta": {...}}`.
Errors reuse the starter's `AppError` handler, so they are
`{"error": "<message>", "detail": "<issues / cause>", "path": "..."}`. Row-level
CSV issues are folded into `detail` as `row N [code] message`, which the
existing frontend `parseErrorBody` already surfaces — no frontend change needed.

**Tenancy.** Every endpoint accepts `org_id` (body or query). In demo mode it is
trusted; when `AUTH_ENABLED=true` it must match the token's `org_id` claim or the
request is refused with 403.

---

## Reused, unchanged

| Endpoint | Purpose |
|---|---|
| `POST /api/upload` | unchanged — RAG document upload. Accepts `.csv`; FLP adds `/api/ingest` for domain ingestion. |
| `POST /api/solve`, `POST /api/solve/stream` | unchanged — the generic agent loop. |
| `GET /api/health`, `/api/health/db`, `/api/health/rag` | unchanged. |

---

## `POST /api/ingest`

Ingest one CSV. Kind is auto-detected from headers unless `kind` is given.

```json
{
  "org_id": "org_demo_cafeteria",
  "csv_text": "date,item_id,location_id,qty_sold\n2026-10-01,itm_cooked_rice,loc_main_canteen,187,false,11220",
  "kind": "sales",
  "source": "uploaded"
}
```

Kinds: `sales`, `inventory`, `items`, `calendar`.

**Response** — `data` carries `inserted`, `updated`, `skipped`, `issues[]`
(each `{row, field, code, message}`), `issue_count`, `ok`, `source`.

Issue codes: `missing_columns`, `unknown_kind`, `unknown_item`,
`unknown_location`, `negative_quantity`, `invalid_date`, `invalid_range`,
`bad_type`, `duplicate`, `missing_value`.

Missing required columns or an unidentifiable file → **422**. Row-level problems
are returned in the body (with `ok: false`) so the caller can fix the exact
lines. Re-uploading the same natural key **updates** rather than duplicating.

Accepted header aliases: `Sales Date`→`date`, `SKU`→`item_id`, `Site`→`location_id`,
`Sold`→`qty_sold`, `On Promo`→`promo_flag`, `Lot`→`batch_id`, `Use By`→`expires_at`, …

## `POST /api/ingest/batch`

`{"files": [<IngestRequest>, …]}` — several CSVs in one transaction.

---

## `POST /api/demo/seed`

Load the labelled synthetic corpus.

```json
{"org_id": "org_demo_cafeteria", "history_days": 56, "seed": 20261003, "reset": true}
```

Every row is written with `source='synthetic'` and the org is created with
`type='demo'`. `history_days` must be ≥ 35 (lag-14 + the 28-day rolling mean + a
4-week backtest).

## `POST /api/demo/scenario`

The whole story in one call: seed → forecast → risk → agent + validator →
forecast listing → staff confirm → impact → withdraw a listing as a false alarm.

```json
{"as_of": "2026-10-03T06:00:00Z", "seed": 20261003, "confirm": true, "withdraw_one": true}
```

Pin `as_of` for a reproducible run. Returns per-step `status` (`ok` / `refused` /
`skipped` / `failed`), a `narrative` for a presenter, and explicit
`what_is_real` / `what_is_simulated` lists.

---

## `POST /api/forecast`

Fit or refresh forecasts.

```json
{"org_id": "...", "location_id": null, "horizon_days": 7, "include_backtest": true}
```

**Response** — `data`: `model`, `model_version`, `calibration`, `rows_written`,
`cold_start_series`, `model_error`, `quantiles`, `baseline`, `evaluation`
(per-section 7 of the ML doc), and `data_provenance`
(`contains_synthetic_data`, `synthetic_fraction`).

Runs fully offline. Without scikit-learn every series uses the cold-start path and
says so in `model_error` and on each row.

`model_error` is non-empty when the model could not be fitted — the forecast is
still returned, cold-start labelled. A **422** with `"No sales history"` means
there is genuinely nothing to model.

## `GET /api/forecast`

Read stored rows. Query: `org_id`, `item_id`, `location_id`, `start`, `end`.

---

## `GET /api/risk`

Ranked risk board.

Query: `org_id`, `location_id`, `batch_id`, `min_risk` (0–1), `limit`, `recompute`.

Each item: `stock_qty`, `expected_demand{p10,p50,p90}`, `expected_unsold`, `risk`,
`urgency_hours`, `donate_by`, `priority`, `value_at_risk`, `status`
(`expired|critical|high|moderate|low`), `safe_to_donate`, `redistributable`,
`insufficient_history`, `model_version`.

`data.safety_config` echoes the active windows so a UI can show why `donate_by`
is what it is, with the note that it is *never* `expires_at`.

---

## `POST /api/recommend`

Run the agent for the highest-priority at-risk batches.

```json
{"org_id": "...", "location_id": null, "batch_id": null, "min_risk": 0.0, "limit": 5, "persist": true}
```

Each recommendation contains `action`, `batch_id`, `quantity`, `deadline`,
`rationale`, `step`, `step_stage`, `evidence`, `tool_trace`, `agent_trace`,
`validation_status`, `validation_issues`, `recovery_plan`, `llm_used`,
`llm_provider`.

A batch typically produces **two** recommendations — a primary step and a
residual step (e.g. transfer 110, donate the remaining 129) — each validated
independently. `data.validator_passed` / `data.validator_rejected` split them.

## `POST /api/recommend/stream`

SSE. Emits, as the work actually happens:
`start`, `risk` ("waste risk computed"), `planner`, `actions` ("evaluating
actions"), `step` (per agent node), `validator` ("safety validation"), `replan`
(only if a replan occurred), `recommendation` ("recommendation ready"), and
`error` on failure. Same headers and framing as `/api/solve/stream`.

No scripted progress ticker; no event is emitted for work that did not happen.

---

## `POST /api/surplus`

Single entry point for the listing lifecycle.

```json
{"action": "create|confirm|withdraw|status",
 "org_id": "...", "batch_id": "bat_demo_rice_001", "listing_id": null,
 "qty": null, "confidence": null, "confirmed_qty": null,
 "confirmed_by": null, "reason": "surplus_did_not_materialise", "record_impact": true}
```

* `create` requires `batch_id`; the others require `listing_id` (else **422**).
* `create` requires a **validated donate recommendation** → **403** otherwise.
* `create` re-checks the live clock at the adapter boundary → **422**
  `SAFETY_VIOLATION` if `donate_by` has passed since approval.
* `confirm` sets `confidence = 1.0` and (unless `record_impact: false`) books an
  impact event.
* `withdraw` sets `confidence = 0.0`, records `false_alarm: true`, and books **no**
  impact — a prediction that was wrong must not inflate the numbers.

Convenience aliases: `POST /api/surplus/create`, `POST /api/surplus/{id}/confirm`,
`POST /api/surplus/{id}/withdraw`, `GET /api/surplus`, `GET /api/surplus/{id}`
(`?refresh=true` also asks FoodLink for its view).

`meta.foodlink` reports the adapter mode and — critically —
`real_foodlink_executed: false` in demo mode.

---

## `GET /api/impact`

Query: `org_id`, `location_id`, `action`, `period`, `since`, `until`, `limit`.

**Response** — `totals`, `by_action`, `by_location`, `by_day`, `factors`
(emission factor, kg/meal, and a note that they are indicative), `accounting_rules`,
`false_alarm_stats`, and `computed_by: "flp.impact (deterministic; never the LLM)"`.

`false_alarm_stats.false_alarm_rate = withdrawn / (confirmed + withdrawn)`.

Compost/animal-feed is recorded with `kg_saved = 0` and `meals = 0`: waste that
was handled is not food that was rescued, and reporting it otherwise would be a
false claim.

---

## `GET /api/health/flp`

Module status: DB connectivity and table count, ML availability and model kind,
the active safety config, impact factors, adapter capability, and the registered
tool list. Also states explicitly what is real and what is simulated.

Never returns a credential — only whether one is present.

---

## Errors

| Status | When |
|---|---|
| 403 | Listing without a validated donate recommendation; cross-tenant `org_id` under `AUTH_ENABLED` |
| 404 | Unknown batch / item / location / listing **within the caller's org** |
| 409 | Illegal listing state transition; FoodLink rejected the call |
| 422 | Validation failure, safety violation, cold start with no data, missing `batch_id`/`listing_id`, invalid date |
| 503 | Optional dependency missing; FoodLink contract not configured; adapter disabled |

The 404-vs-403 split is deliberate: a resource in another organization returns
**422 with a generic "not found" message**, identical to one that never existed,
so the API cannot be used to probe other tenants.