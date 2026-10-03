# FoodLink Predict — ML notes

Everything here is honest about what it is. Where a number is an approximation,
it says so and explains why.

---

## 1. Granularity and why quantiles

One forecast per **ITEM × LOCATION × DAY**, with **P10 / P50 / P90**.

Quantiles rather than a point estimate because the two consumers want opposite
things:

* **Buying / prepping** wants the upside (P50–P90) so it does not stock out.
* **Waste risk** wants the downside (P10–P50), because surplus only exists if
  demand comes in low.

A single point estimate cannot serve both, so it is not used anywhere.

---

## 2. Baseline (mandatory)

**Seasonal-naive, lag-7**: the same weekday one week earlier. It is always
computed, for every series and every forecast date, and it is the bar the model
has to clear. If the model cannot beat it, that is reported — the backtest
returns `model_better: false` rather than being quietly redefined.

A series with no value 7 days back gets `0.0` from the baseline, and the
caller must treat that as *no baseline available*, not *zero demand*.

---

## 3. Features

Fixed order (`features.FEATURE_NAMES`), part of the persisted model contract:

| Feature | Note |
|---|---|
| `day_of_week`, `month`, `day_of_month`, `week_of_year`, `is_weekend` | calendar |
| `is_holiday`, `days_to_holiday` | from `calendar_days`; `days_to_holiday` is **derived**, not stored, so it stays correct when a calendar is re-uploaded |
| `lag_7`, `lag_14` | prior weeks only |
| `roll_mean_7`, `roll_mean_28` | trailing windows, exclusive of the target |
| `promo_flag` | target day when observed, else the last known value — never a guessed future promo |
| `trend_index` | length of available history |
| category, location | one-hot by the model wrapper |
| weather | **optional**; omitted entirely when absent rather than imputed |

### Leakage rule

Only rows **strictly before** the target date are ever indexed. This is enforced
in one place (`features.feature_row`) and covered by tests that mutate the
target day's own value and assert the feature vector does not change.

---

## 4. Model

**Default: quantile gradient boosting.** Three `GradientBoostingRegressor`
heads at `alpha = 0.1 / 0.5 / 0.9`, `loss="quantile"` (scikit-learn ≥ 1.0). This
is genuine quantile regression, not a symmetric interval around a point.

Hyper-parameters are **fixed**, not tuned per request — a hackathon demo must be
reproducible, and a silent per-request search makes results unstable:

```
n_estimators=250, learning_rate=0.06, max_depth=3,
min_samples_leaf=8, subsample=0.9, random_state=42
```

**Alternative: random forest** (`FORECAST_MODEL=random_forest`). A forest has no
native quantile loss, so quantiles are the 10th/50th/90th percentiles across the
trees. That is a standard cheap approximation and is documented as one; it is not
the default precisely because gradient boosting does not need it.

**Model version** is content-addressed (`stable_version` over features, model,
params, vocabulary, series). An unchanged retrain therefore produces the *same*
version string and is visibly a no-op instead of silently minting a new version.

---

## 5. Quantile calibration

Quantile heads fitted on a modest number of series are systematically
**under-dispersed**, which would make every batch look low-risk — the exact
failure this product must not have.

So after fitting, the last 20% of training samples (chronological holdout) are
scored by the P50 head and the 10th/90th percentiles of those residuals become
additive offsets applied to P10/P90. Purely deterministic, no randomness, and
`calibration_summary()` reports the holdout size and the offsets so the widening
is visible rather than hidden.

`enforce_quantile_order` then projects the result onto the monotone cone: after
correction `p10 <= p50 <= p90` always holds and all three are ≥ 0.

---

## 6. Cold start

A series with fewer than `FORECAST_COLD_START_DAYS` (default 14) **never calls
the model**. It uses a shrinkage fallback blending category mean, location mean
and global mean, with a single weekend adjustment, and a deliberately wider band
(`p10 = 0.55·p50`, `p90 = 1.75·p50`) because we genuinely know less.

Such rows are persisted with `method='cold_start'` and that label is returned on
every API response. A cold-start forecast is **not** sufficient evidence for a
donation: the validator rejects it with `insufficient_history`.

Without scikit-learn installed, *every* series takes this path — degraded but
labelled, never silently wrong.

---

## 7. Evaluation

Rolling-origin backtest over the last 28 days.

* The origin advances daily; the fit is refreshed every 7 days
  (`refit_every_days`) — the usual runtime/fidelity compromise.
* The model is fit on **all series pooled**, truncated to dates strictly before
  the origin, which is exactly how it is fit in production. Fitting per-series on
  a short rolling prefix would leave each fit with ~14 rows and produce a score
  that describes the window size rather than the model.
* Any point whose prefix cannot be trained falls back to the baseline and is
  **counted** in `baseline_fallback_points`.

### Metrics

* **WAPE** = `Σ|y − ŷ| / Σ|y|`. Returns `0.0` for an all-zero actual series
  instead of dividing by zero (a correct zero-demand forecast is not an error).
* **Bias** = `Σ(ŷ − y) / Σ|y|`, signed: positive means over-forecasting.
* **sMAPE**, reported alongside so a single near-zero day cannot make WAPE look
  catastrophic. Note sMAPE is *scale*-invariant, not symmetric about the
  midpoint — a known quirk of the definition.

The response always contains `model`, `baseline` and `improvement_vs_baseline`
(`wape_absolute`, `wape_relative`, `model_better`). If there is not enough
history to evaluate at all, the report returns `available: false` with a reason
— never a flattering zero.

---

## 8. Waste risk

Plain code, no model, unit-tested per the brief.

```
expected_demand  = Σ forecast demand from now until EXPIRY   (P10 / P50 / P90)
expected_unsold  = max(0, stock − expected_demand)
risk             = P(demand_until_expiry < stock)
urgency_hours    = hours until donate-by
priority         = risk × value_at_risk          (tie-broken by urgency)
```

**Demand accumulates to expiry, the deadline is donate-by.** Clearing stock by
sale and rescuing it are different problems on different clocks; using donate-by
for both would silently zero same-day demand.

### Multi-day spread

Summing per-day quantiles understates uncertainty, because day-to-day errors do
not cancel perfectly. Each day's implied sigma is derived from its own
P10…P90 span (`σ = (p90 − p10) / 2.5632`) and combined as
`sqrt(Σ σ²)` under an **independent-days assumption** — standard, deterministic,
and documented rather than assumed away. A relative floor
(`MIN_RELATIVE_SIGMA = 0.05`) prevents a perfectly smooth forecast from implying
certainty.

`risk = Φ((stock − μ) / σ)`, clamped to **[0.01, 0.99]**: a forecast is never
proof, and reporting a hard 1.00 would flatten every batch into one bucket.

### donate-by ≠ expires-at

```
shelf-life limit = prepared_at + safe_window(food_class)
safety limit     = min(expires_at, shelf-life limit)
donate_by        = safety limit − pickup_lead_time_hours
```

An **unmapped food class gets the shortest configured window**, never a
generous default. Every rule that can authorise a donation is checked twice: once
in `compute_donate_by`, and again immediately before publishing.

---

## 9. Honest limitations

* The independent-days variance assumption understates spread when consecutive
  days are strongly autocorrelated. Quantile calibration partly compensates, but
  the assumption is real and stated.
* Holiday handling uses a binary flag plus distance-to-next-holiday. A holiday
  *type* multiplier (a religious fast vs a public holiday) is not modelled.
* Weather is an optional scalar from a small lookup; it is omitted, not
  imputed, when absent.
* The default safe windows are **indicative defaults, not certified food-safety
  guidance.** They must be reviewed for the deployment jurisdiction.
* The emission factor is a configurable planning figure, not a lifecycle
  assessment. It is printed in every `/api/impact` response for that reason.