# FoodLink Predict — demo, configuration and testing

---

## 1. Run the demo (offline, no keys, no database server)

```bash
cd backend
pip install -r requirements.txt                 # core starter deps
pip install -r requirements-foodlink-predict.txt # optional: real forecasting
uvicorn app.main:app --port 8000
```

Then either open `http://localhost:8000/docs` and call

```
POST /api/demo/scenario
{"as_of": "2026-10-03T06:00:00Z", "seed": 20261003}
```

or run it headless:

```bash
python -c "
from app.projects.foodlink_predict.demo import scenario
import json; print(json.dumps(scenario.run('org_demo_cafeteria', as_of='2026-10-03T06:00:00Z'), indent=2, default=str))
"
```

### What happens

| # | Step | Result |
|---|---|---|
| 1 | seed synthetic data | 560 sales rows, 5 items, 2 locations, 7 batches, 70 calendar days |
| 2 | demand forecast | WAPE vs seasonal-naive on a rolling-origin backtest |
| 3 | waste-risk board | ranked batches with risk, urgency, donate-by |
| 4 | agent + validator | e.g. transfer 110 → donate the remaining 129 |
| 5 | forecast listing | `status=forecast`, `real_foodlink_executed=false` |
| 6 | staff confirm | `confidence=1.0`, impact booked |
| 7 | second listing | published |
| 8 | withdraw it | logged as a false alarm, **no impact booked** |
| 9 | impact ledger | kg / meals / money / CO2e + false-alarm rate |

### The story it tells

> A cafeteria prepared 240 cooked-rice meals. The forecast expects 137 to go
> unsold (risk 0.99, donate-by in 3 hours). The ladder's first rung — transfer to
> the annex canteen, which has real forecast headroom — moves 110 portions. The
> remainder is re-scored against the same demand distribution and the only legal
> action left is donation. The agent publishes a **forecast** listing, staff
> confirms the actual quantity, and impact is booked for the confirmed amount
> only.

### Determinism

Same `as_of` + same `seed` → identical numbers. `random.Random(seed)` drives all
noise; the model version is content-addressed. `test_demo_scenario_is_deterministic`
asserts this.

`as_of` also anchors the inventory timestamps, so the demo's donate-by is
relative to *when it runs* — not to midnight, which would make the output depend
on the hour of day.

---

## 2. What is real, what is mocked, what is synthetic

| | Status |
|---|---|
| Demand forecasting (P10/P50/P90) | **REAL** — quantile gradient boosting, or a labelled cold-start fallback |
| Backtest, WAPE, bias, baseline comparison | **REAL** — rolling-origin, no leakage |
| Waste risk, urgency, donate-by, priority | **REAL** — deterministic code |
| Action ladder and recovery sequencing | **REAL** — deterministic code |
| Safety validator | **REAL** — deterministic code, LLM-immune |
| Impact arithmetic | **REAL** — deterministic code |
| Listing state machine, idempotency, conflicts | **REAL** |
| Tenant isolation | **REAL** — enforced in the query layer |
| **All input data** | **SYNTHETIC** — seeded RNG; `source='synthetic'`, org `type='demo'` |
| **LLM selection + rationale** | **MOCK** in demo mode (`LLM_PROVIDER=mock`); every number is still deterministic |
| **FoodLink hand-off** | **SIMULATED** — `demo=true, simulated=true, real_foodlink_executed=false` |
| **FoodLink's six agents** | **NOT RUN.** They live in the FoodLink system, which this codebase cannot see |
| **Transfer ETA** | **ESTIMATED** — `haversine / transport_kmh`, labelled `estimated`; the starter has no routing provider |
| **CO2e / meals factors** | **INDICATIVE** — configurable, printed in every `/api/impact` response |

No response in this module ever presents a simulated value as a real one.

---

## 3. Configuration

All optional. Every default leaves the starter's behaviour unchanged. Full
comments in `backend/.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `FOODLINK_PREDICT_ENABLED` | `true` | Mount the FLP routes. `false` restores the original surface. |
| `DEMO_MODE` | `true` | Response labelling only; enforcement is unconditional. |
| `ML_PROVIDER` | `sklearn` | ML backend marker. |
| `FORECAST_MODEL` | `gradient_boosting` | or `random_forest`. |
| `FORECAST_COLD_START_DAYS` | `14` | Below this, cold-start fallback. |
| `FOODLINK_PREDICT_DB_URL` | *(own SQLite file)* | Deliberately **not** `DATABASE_URL`, so FLP never disturbs the starter's DB config. |
| `FOODLINK_ADAPTER_MODE` | `demo` | `demo` \| `http` \| `disabled`. |
| `FOODLINK_API_URL` | *(empty)* | Required for `http`. |
| `FOODLINK_LISTING_PATH` | *(empty)* | Required for `http`. **Intentionally no default** — any default would be a guessed production path. |
| `FOODLINK_API_KEY` | *(empty)* | Read only in `adapters/factory.py`; logged only via `redact()`. |
| `SAFE_WINDOWS_JSON` | *(built-in defaults)* | `{"cooked":24,...}` hours per food class. |
| `PICKUP_LEAD_TIME_HOURS` | `6` | FoodLink pickup lead time. |
| `EMISSION_FACTOR_CO2E` | `2.5` | kg CO2e per kg diverted. |
| `KG_PER_MEAL` | `0.35` | kg per meal-equivalent. |
| `SUPABASE_ENABLED` | `false` | Starter setting; RLS template in `database/schema.sql`. |

**No secrets are hardcoded. Nothing secret is needed by the frontend.**

### Defaults that are *not* production-ready

`DEFAULT_SAFE_WINDOWS_HOURS` and the impact factors are **indicative defaults,
not certified guidance.** An operator must set them for their jurisdiction before
live use. They are surfaced in `GET /api/risk` and `GET /api/impact` so a UI can
display them rather than hiding the assumption.

---

## 4. Testing

```bash
cd backend

# FLP suite only
python -m pytest tests/flp -q

# Whole backend, including every pre-existing V4 test
LLM_PROVIDER=mock python -m pytest . -q
```

> Set `LLM_PROVIDER=mock` for a deterministic offline run. With a live provider
> configured, `tests/test_intake.py` calls the real API and fails on rate limits —
> a pre-existing condition unrelated to this project.

### Coverage

| File | Focus |
|---|---|
| `test_flp_forecast.py` | baseline, WAPE/bias/sMAPE, leakage, cold start, quantile hygiene, backtest honesty |
| `test_flp_risk.py` | donate-by ≠ expiry, safety windows, urgency, priority + tie-break, residual re-scoring, invalid config |
| `test_flp_actions.py` | every ladder rung allow/deny + the reason, discount caps, ETA feasibility |
| `test_flp_validator.py` | every rejection rule, the publish-time gate, and "a generous LLM cannot win" |
| `test_flp_adapter.py` | interface, state machine, idempotency, **"the HTTP adapter refuses to guess"** |
| `test_flp_impact.py` | conversions, compost is not credited as rescued, factor configurability |
| `test_flp_ingest.py` | kind detection, every issue code, aliases, upserts, provenance labelling |
| `test_flp_security.py` | tenant isolation at DB *and* API level, cross-tenant refusal, secret non-exposure |
| `test_flp_integration.py` | the whole workflow stage by stage, plus SSE events and the demo |

### Test design notes

* FLP fixtures live in `tests/flp/conftest.py` with an **autouse** per-test
  SQLite file. No repo-root `conftest.py` was added, because the starter's own
  tests build their app at import time and a root autouse fixture would change
  their behaviour.
* Tests that pin a clock pin it explicitly; the `seeded` fixture anchors to the
  real clock so donate-by windows are live.
* `app/auth/jwt.py` snapshots settings at import, so the JWT tenancy tests reload
  that module rather than editing V4 core.

---

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `CAPABILITY_UNAVAILABLE` on `/api/forecast` | scikit-learn not installed → `pip install -r requirements-foodlink-predict.txt`. Forecasts still return, labelled cold-start. |
| `forecast WAPE` worse than baseline | Reported honestly as `model_better: false`. Check `baseline_fallback_points` and `n_refits`. |
| Every recommendation is `compost` | Batches are past donate-by. Anchor the demo's `as_of` nearer the run time. |
| `403` on `/api/surplus` create | No validated *donate* recommendation for that batch. Run `/api/recommend` first. |
| `422 SAFETY_VIOLATION` on create/confirm | `donate_by` passed since the recommendation was validated. Expected behaviour — re-run the pipeline. |
| `503 CAPABILITY_UNAVAILABLE` from the adapter | `FOODLINK_ADAPTER_MODE=http` without both URL and path. Use `demo`. |
| `No sales history found` | Nothing ingested. `POST /api/demo/seed` or `/api/ingest`. |