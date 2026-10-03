# FoodLink Predict

AI food waste **prediction, prevention and early redistribution** — built on top
of the Hackathon Starter Toolkit V4.

FoodLink Predict forecasts demand, scores each batch for waste risk, recommends
the best recovery action, and publishes a **forecast surplus listing** that
FoodLink's existing six agents can act on hours before the food is at risk.

```
Sales + Inventory + Shelf life + Calendar
        ↓
Feature preparation  →  Demand forecast (P10 / P50 / P90)
        ↓
Waste-risk engine  →  Action ladder  →  Recommendation agent  →  Hard validator
        ↓
FoodLink-compatible listing  →  FoodLink's six agents (untouched)  →  Impact ledger
```

---

## What is real, what is not

| | |
|---|---|
| Forecasts, WAPE vs baseline, waste risk, donate-by, action ladder, validator, impact arithmetic | **REAL** — deterministic code and models |
| All input data | **SYNTHETIC** — seeded RNG, labelled `source='synthetic'` |
| LLM selection + rationale | **MOCK** offline; every number stays deterministic |
| FoodLink hand-off | **SIMULATED** — stamped `real_foodlink_executed: false` |
| FoodLink's six agents | **NOT RUN** — they live in a system this repo cannot see |
| Transfer ETA | **ESTIMATED** — haversine / assumed speed, labelled as such |

---

## Quick start (fully offline)

```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-foodlink-predict.txt   # optional: real forecasting
uvicorn app.main:app --port 8000
```

```bash
# One call runs the entire story
curl -X POST localhost:8000/api/demo/scenario \
  -H 'Content-Type: application/json' \
  -d '{"as_of":"2026-10-03T06:00:00Z","seed":20261003}'
```

No API keys. No database server. No network.

---

## Documentation

| Document | Contents |
|---|---|
| [`architecture.md`](./foodlink_predict_architecture.md) | V4 audit, what was reused vs added, layer map, data model, design decisions |
| [`api.md`](./foodlink_predict_api.md) | Every endpoint, error codes, SSE events |
| [`ml.md`](./foodlink_predict_ml.md) | Features, baseline, quantiles, calibration, backtest, risk maths, limitations |
| [`agent.md`](./foodlink_predict_agent.md) | Agent graph, validator rules, FoodLink adapter, tenancy |
| [`demo.md`](./foodlink_predict_demo.md) | Demo walkthrough, config table, testing, troubleshooting |

---

## API surface

New: `POST /api/ingest`, `POST /api/forecast`, `GET /api/risk`,
`POST /api/recommend`, `POST /api/recommend/stream`, `POST /api/surplus`,
`GET /api/impact`, `GET /api/health/flp`, `POST /api/demo/seed`,
`POST /api/demo/scenario`.

Reused unchanged: `POST /api/upload`, `POST /api/solve`,
`POST /api/solve/stream`, `GET /api/health`.

---

## The non-negotiables, and where they live

| Rule | Enforced by |
|---|---|
| Numbers come from code or models, never the LLM | `forecast.py`, `risk.py`, `actions.py`; the agent reads them, never writes them |
| The LLM selects and explains only | `agent.py::executor_node` — output overwritten by `proposal_for_step` |
| Decisions are validator-controlled | `validators.py`, two gates (decision time + publish time) |
| Donation safety is a hard gate | `validators.py` + `config.SafetyConfig` |
| The LLM cannot override safety | No code path from the agent to the adapter bypasses `validate()` |
| Every recommendation cites its evidence | `REQUIRED_EVIDENCE_KEYS`, enforced in `validate()` |
| Works offline | `DemoFoodLinkAdapter`, mock LLM, SQLite, synthetic generator |
| Mock LLM stays available | `LLM_PROVIDER=mock`, the starter's own provider |
| Synthetic data is labelled | `source` column, org `type='demo'`, `GET /api/health/flp` |
| No fake real-time data | Every ETA labelled `estimated`; every simulated response stamped |
| No hardcoded secrets | None; `FOODLINK_API_KEY` read once, logged only via `redact()` |
| No frontend secrets | FLP is backend-only |
| No unnecessary dependencies | scikit-learn is an **optional** group; app boots without it |
| V4 APIs preserved | Only `app/main.py` and `app/core/config.py` touched, both additive |
| Toolkit modules reused | config, errors, LLMService, agents, tools registry, maps, auth |
| FoodLink isolated behind one adapter | `app/projects/foodlink_predict/adapters/` |
| Six FoodLink agents untouched | They are not in this repo and were never modified |
| Multi-tenancy organization-scoped | `db.py` helpers + `tenancy.py`; `(org_id, id)` keys |
| `org_id` on tenant rows | Every FLP table carries it |

---

## FoodLink integration status

The real FoodLink listing schema was **never available** to this module — the
architecture PDF says so explicitly. Nothing here guesses it.

`HttpFoodLinkAdapter` **refuses to run** until `FOODLINK_API_URL` *and*
`FOODLINK_LISTING_PATH` are both set, and marks every response
`contract_verified: false`. Wiring the real FoodLink means editing two methods
in `adapters/http.py`. Nothing else changes.

---

## Tests

```bash
cd backend
LLM_PROVIDER=mock python -m pytest tests/flp -q   # this project
LLM_PROVIDER=mock python -m pytest . -q           # + all pre-existing V4 tests
```

Set `LLM_PROVIDER=mock` for a deterministic offline run. With a live provider
configured, two pre-existing `test_intake.py` tests fail on upstream rate limits —
unrelated to this project.