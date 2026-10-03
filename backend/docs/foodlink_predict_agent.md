# FoodLink Predict — agent, validator and FoodLink adapter

---

## 1. Agent

Same shape as the starter's `app/agents/workflow.py`, specialised:

```
PLANNER → TOOLS → EXECUTOR → VALIDATOR → RESPONDER
                        ▲          │
                        └─ replan ┘   (max 1)
```

Reused from V4: `MAX_STEPS` (5), the node/trace/step record format
(`node`, `output_summary`, `tool_name`, `duration_ms`), the shared
`TOOL_REGISTRY`, `_extract_json_object` for JSON repair, `LLMService`, and the
LangGraph `StateGraph` + `_SequentialFallback` construction.

### The TOOLS phase is deterministic

It is deliberately **not** LLM-routed. Evidence gathering always runs
`get_forecast` → `get_risk_items` → `rank_actions`. Letting a model decide which
tools to skip would let it recommend without evidence — which the validator would
reject anyway, just less clearly.

### What the LLM may do

* pick **one** action from the validator-approved list;
* write a rationale in plain language.

### What it may not do

* compute or restate a forecast, risk, quantity, date or score;
* choose an action outside the allowed set;
* reach the validator (there is no code path around it);
* override a safety gate.

Enforcement is structural, not a prompt instruction:

1. The ladder marks what is allowed.
2. `build_proposal` assembles the proposal from the **evidence bundle**.
3. `proposal_for_step` overwrites `action`, `quantity` and `deadline` from the
   deterministic plan *after* the LLM has spoken.
4. `validate()` re-checks the result against live state.

If the LLM proposes an action outside the allowed set, it is **discarded**, the
deterministic default is used, and the override is recorded in `llm_error` rather
than hidden.

### Rationale lint

`lint_rationale` extracts every number from the rationale and checks each one
appears in the evidence blob. Unsourced numbers are reported in
`metadata.rationale_lint` (`passed: false`, `unsourced_numbers: [...]`).

This is defence in depth, not proof: it shows a number was *sourced from tool
output*, not that it is meaningful. It cannot be, and does not claim to be.

### Recovery sequences

One agent turn can produce a multi-step plan. `service.build_recovery_plan`
applies the ladder **sequentially over quantity**: each accepted step consumes
stock, then the next step is evaluated against `risk.assess_residual`, which
reuses the same demand distribution (the forecast window has not changed) and
only re-compares it against the smaller quantity.

That is what produces "transfer 110, donate the remaining 129". Each step becomes
its own `Recommendation` row and is validated independently, so a rescue can never
ride on the approval of an unrelated earlier step.

---

## 2. Validator — the hard gate

`validators.py`. Deterministic, LLM-immune, and the only path to a listing.

### Rules

| Rule | Rejects when |
|---|---|
| `donation_past_donate_by` | `donate_by` missing or in the past |
| `expired_batch` | `expires_at` in the past |
| `food_class_unsafe` | class not on the redistributable list |
| `quantity_exceeds_stock` | requested > stock on hand |
| `quantity_not_positive` | ≤ 0, non-numeric, or boolean |
| `missing_evidence` | forecast / risk / tool_calls not all cited |
| `missing_forecast` | no forecast rows, or all `p50 == 0` |
| `invalid_location` | donation without a resolvable pickup location |
| `invalid_batch` | unresolvable batch, unknown stock, missing urgency |
| `unsafe_storage_state` | unknown storage, or class not permitted in it |
| `invalid_action` | off-ladder action; compost while food is still safe |
| `insufficient_history` | donation justified by cold-start data |

A valid donation must satisfy all of them.

### Storage integrity

`STORAGE_ALLOWED_CLASSES` encodes which classes may travel in which mode
(`hot`→cooked, `ambient`→packaged/produce, …). A mismatch is refused: an
unverified handling chain cannot be donated, even if the food itself is fine.

### Two gates, deliberately

* `validate()` — at decision time, using the same clock reference as the risk
  assessment. Passing the assessment's `now` through matters: using `utcnow()`
  here would let the validator disagree with the evidence it is checking, so a
  batch could be scored safe and rejected seconds later purely on elapsed time.
* `can_publish_listing()` — at publish time, against the live clock. A
  recommendation approved an hour ago may now be past its `donate_by`; without
  this gate, a stale approval could be redeemed into a live listing.

### On failure

The agent replans once with the rejection reasons injected. If it fails again,
the recommendation is persisted as `status='rejected'` with its full error list.
**Rejections are auditable, not discarded** — an audit trail of refusals is worth
more than a tidy success list.

---

## 3. FoodLink adapter — the single seam

### The honest position

**The real FoodLink listing schema was never available to this module.** The
architecture PDF says so explicitly, and the FoodLink six agents
(detect / match / negotiate / hand off / deliver / verify) exist in a system this
codebase cannot see. Nothing here guesses their schema.

### Interface

```python
class FoodLinkAdapter(Protocol):
    def create_forecast_listing(self, listing: dict) -> dict: ...
    def confirm_listing(self, listing_id: str, *, confirmed_qty=None, confirmed_by=None) -> dict: ...
    def withdraw_listing(self, listing_id: str, *, reason=...) -> dict: ...
    def get_listing_status(self, listing_id: str) -> dict: ...
```

`canonical_listing()` defines Predict's own versioned document
(`contract_version: "flp-listing/1"`), matching the PDF's proposed shape.

### Statuses

| Status | Meaning | FoodLink's side |
|---|---|---|
| `forecast` | Predicted surplus, **no commitment** | Detect pre-warns NGOs/volunteers |
| `confirmed` | Staff verified actual quantity, `confidence = 1.0` | Normal detect→…→verify flow |
| `withdrawn` | Sales caught up, surplus never existed | Release reservations, log the false alarm |

Transitions are enforced (`forecast → confirmed|withdrawn`, `confirmed →
withdrawn`, `withdrawn → ∅`); an illegal move is a 409.

### `DemoFoodLinkAdapter` (default, `FOODLINK_ADAPTER_MODE=demo`)

In-memory, offline, deterministic. It simulates FoodLink *receiving* a listing.
Every response is stamped:

```
demo: true, simulated: true, executed_by: "demo-simulator",
real_foodlink_executed: false, note: "No FoodLink agent ran and no data left this process."
```

`expected_foodlink_behaviour` states what a real FoodLink *would* be expected to
do next, labelled as an expectation rather than a result.

Duplicate publishes are idempotent when the content hash matches, and a conflict
when it does not.

### `HttpFoodLinkAdapter` (`FOODLINK_ADAPTER_MODE=http`)

**Refuses to run** until both `FOODLINK_API_URL` and `FOODLINK_LISTING_PATH` are
set. There is deliberately no default path, because any default would be a guess
at someone else's production API.

If a path *is* configured, it POSTs the canonical document verbatim and marks
every response `contract_verified: false` with the note *"Sent to FoodLink using
the UNVERIFIED proposed contract. Confirm the field mapping before relying on
this."*

### To wire the real FoodLink

Edit two methods in `adapters/http.py`:

```python
def map_to_foodlink_payload(self, listing: dict) -> dict:  # canonical -> theirs
def parse_response(self, payload: Any) -> dict:            # theirs -> ours
```

No route, model, agent, migration or test elsewhere changes. That is the whole
point of keeping this boundary to one package: **if the schema differs, exactly
one file changes.**

### Confidence semantics

A forecast listing's `confidence` is **P(the surplus materialises)** — which is
the waste-risk score. A high-risk batch therefore carries *high* confidence that
surplus will exist. The inverse would tell FoodLink the batches most likely to
need rescuing are the least certain, which is the opposite of what the number
means. Staff confirmation pins it to `1.0`, because a verified quantity is no
longer a prediction.

---

## 4. Multi-tenancy

* Tenant scope is derived from the JWT `org_id` claim when `AUTH_ENABLED=true`;
  a body/query `org_id` that disagrees is **refused**, never downgraded.
* A token with no `org_id` claim cannot scope anything and is refused.
* Every read goes through `db.py` helpers that take `org_id`. There are no ORM
  relationships between tenant-scoped tables, so there is no "forgot the filter"
  code path.
* A resource in another organization returns a generic "not found" (422), worded
  identically to one that never existed, so the API cannot probe other tenants.
* Tenant tables are keyed `(org_id, id)`, so `loc_main_canteen` can exist
  independently in two organizations.
* RLS policies for Supabase are included (commented) at the end of
  `database/schema.sql`.