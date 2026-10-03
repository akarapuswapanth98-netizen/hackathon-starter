"""Orchestration: the pipeline the PDF describes, wired to the toolkit.

    sales + inventory + calendar
      -> features -> forecast (P10/P50/P90)
      -> waste risk -> action ladder
      -> recommendation agent -> validator
      -> FoodLink listing -> impact

Every numeric stage is deterministic. The agent sits only between the ladder and
the validator, where it may pick an action and write prose.

All queries are org-scoped. There is no code path in this module that can read
another tenant's rows.
"""

from __future__ import annotations

import datetime as _dt
import logging
import time
from typing import Any

from sqlalchemy import select

from app.projects.foodlink_predict import actions as A
from app.projects.foodlink_predict import forecast as F
from app.projects.foodlink_predict import impact as I
from app.projects.foodlink_predict import risk as R
from app.projects.foodlink_predict import validators as V
from app.projects.foodlink_predict.agent import proposal_for_step, step_rationale
from app.projects.foodlink_predict.config import (
    ACTION_BUY_PREPARE_LESS,
    ACTION_DONATE,
    SafetyConfig,
    get_safety_config,
)
from app.projects.foodlink_predict.db import get_by_id, list_where, require_by_id, session_scope
from app.projects.foodlink_predict.errors import ColdStart, NotFound, ValidationFailed
from app.projects.foodlink_predict.models import (
    Batch,
    CalendarDay,
    Forecast,
    Item,
    Location,
    Recommendation,
    SalesDaily,
    WasteRisk,
    utcnow,
)
from app.projects.foodlink_predict.tenancy import ensure_org_exists
from app.projects.foodlink_predict.util import as_utc, date_range, iso, new_id, stable_version

logger = logging.getLogger("flp.service")


# --------------------------------------------------------------------------
# Forecast
# --------------------------------------------------------------------------
def run_forecast(
    org_id: str,
    *,
    location_id: str | None = None,
    horizon_days: int = 7,
    as_of: _dt.datetime | None = None,
    include_backtest: bool = True,
    safety: SafetyConfig | None = None,
) -> dict:
    """Fit (or reuse) a forecaster and persist P10/P50/P90 for the horizon.

    Returns the persisted rows plus an honest evaluation block. When sklearn is
    absent this still runs: every series falls back to the cold-start/shrinkage
    path and ``method`` says so on each row.
    """
    safety = safety or get_safety_config()
    ref = as_utc(as_of) or utcnow()
    ensure_org_exists(org_id)

    with session_scope() as sess:
        cal_rows = list_where(sess, CalendarDay, org_id)
        calendar = F.calendar_index(cal_rows)
        series = F.load_series(sess, org_id)
        if location_id:
            series = [s for s in series if s.location_id == location_id]
        if not series:
            raise ColdStart(
                "No sales history found for this organization. Upload a sales CSV (POST /api/ingest) "
                "or load the synthetic demo dataset first."
            )

        model = None
        model_error = ""
        if F.sklearn_available():
            try:
                model = F.QuantileForecaster().fit(series, calendar)
            except (ColdStart, Exception) as exc:  # noqa: BLE001
                # Fall through to cold start rather than 500: a partial answer
                # with method='cold_start' beats no answer at all.
                logger.warning("forecast fit failed, using cold start: %s", exc)
                model_error = f"{type(exc).__name__}: {exc}"
        else:
            model_error = "scikit-learn not installed; all series use the cold-start fallback"

        priors = F.compute_priors(series)
        # Per-series priors beat the global mean for short histories.
        results: list[F.SeriesResult] = []
        for s in series:
            cat_mean = priors.get("_per_category", {}).get(s.category, priors.get("category_mean"))
            loc_mean = priors.get("_per_location", {}).get(s.location_id, priors.get("location_mean"))
            local_priors = {
                "category_mean": cat_mean,
                "location_mean": loc_mean,
                "global_mean": priors.get("global_mean", 0.0),
            }
            results.append(
                F.forecast_series(
                    s,
                    horizon_days,
                    calendar,
                    model=model,
                    cold_start_days=safety.cold_start_days,
                    priors=local_priors,
                    as_of=ref.date(),
                )
            )

        written = 0
        version_tags: set[str] = set()
        for res in results:
            for point in res.points:
                existing = (
                    sess.query(Forecast)
                    .filter(
                        Forecast.org_id == org_id,
                        Forecast.item_id == point.item_id,
                        Forecast.location_id == point.location_id,
                        Forecast.target_date == point.target_date,
                        Forecast.model_version == point.model_version,
                    )
                    .one_or_none()
                )
                if existing is not None:
                    existing.p10, existing.p50, existing.p90 = point.p10, point.p50, point.p90
                    existing.method = point.method
                else:
                    sess.add(
                        Forecast(
                            org_id=org_id,
                            item_id=point.item_id,
                            location_id=point.location_id,
                            target_date=point.target_date,
                            p10=point.p10,
                            p50=point.p50,
                            p90=point.p90,
                            model_version=point.model_version,
                            method=point.method,
                        )
                    )
                written += 1
                version_tags.add(point.model_version)
        sess.flush()

        backtest = F.backtest(series, calendar, test_days=28, cold_start_days=safety.cold_start_days) if include_backtest else {"available": False, "reason": "skipped by caller"}

        cold = [r for r in results if r.method == "cold_start"]
        return {
            "org_id": org_id,
            "as_of": iso(ref),
            "horizon_days": horizon_days,
            "series_count": len(series),
            "rows_written": written,
            "model": (model.kind if model else "none"),
            "model_version": sorted(version_tags)[0] if version_tags else "unknown",
            "model_versions": sorted(version_tags),
            "calibration": model.calibration_summary() if model else None,
            "cold_start_series": [r.label() for r in cold],
            "cold_start_days_threshold": safety.cold_start_days,
            "model_error": model_error,
            "quantiles": {"p10": "10th percentile", "p50": "median", "p90": "90th percentile"},
            "baseline": "seasonal_naive_lag7 (same weekday, previous week)",
            "evaluation": backtest,
            "data_provenance": _provenance(sess, org_id),
        }


def _provenance(sess, org_id: str) -> dict:
    """How much of this org's data is synthetic. Surfaced on every forecast."""
    rows = sess.execute(select(SalesDaily.source).where(SalesDaily.org_id == org_id)).scalars().all()
    total = len(rows)
    synthetic = sum(1 for r in rows if r == "synthetic")
    return {
        "sales_rows": total,
        "synthetic_rows": synthetic,
        "uploaded_rows": total - synthetic,
        "synthetic_fraction": round(synthetic / total, 4) if total else 0.0,
        "contains_synthetic_data": synthetic > 0,
    }


def stored_forecast(
    org_id: str,
    *,
    item_id: str | None = None,
    location_id: str | None = None,
    start: _dt.date | None = None,
    end: _dt.date | None = None,
) -> list[dict]:
    """Read persisted forecast rows (the source for the risk engine)."""
    with session_scope() as sess:
        stmt = select(Forecast).where(Forecast.org_id == org_id)
        if item_id:
            stmt = stmt.where(Forecast.item_id == item_id)
        if location_id:
            stmt = stmt.where(Forecast.location_id == location_id)
        if start:
            stmt = stmt.where(Forecast.target_date >= start)
        if end:
            stmt = stmt.where(Forecast.target_date <= end)
        rows = list(sess.execute(stmt.order_by(Forecast.target_date)).scalars().all())
        # Latest model_version wins per target date.
        newest: dict[_dt.date, Forecast] = {}
        for r in rows:
            newest.setdefault(r.target_date, r)
        return [
            {
                "target_date": d,
                "p10": float(r.p10),
                "p50": float(r.p50),
                "p90": float(r.p90),
                "model_version": r.model_version,
                "method": r.method,
            }
            for d, r in sorted(newest.items())
        ]


# --------------------------------------------------------------------------
# Risk
# --------------------------------------------------------------------------
def compute_risk(
    org_id: str,
    *,
    batch_id: str | None = None,
    location_id: str | None = None,
    persist: bool = True,
    as_of: _dt.datetime | None = None,
    safety: SafetyConfig | None = None,
) -> list[R.RiskAssessment]:
    """Score every live batch in the tenant (or one batch)."""
    safety = safety or get_safety_config()
    ref = as_utc(as_of) or utcnow()

    with session_scope() as sess:
        stmt = select(Batch).where(Batch.org_id == org_id)
        if batch_id:
            stmt = stmt.where(Batch.id == batch_id)
        if location_id:
            stmt = stmt.where(Batch.location_id == location_id)
        batches = list(sess.execute(stmt).scalars().all())
        if not batches:
            return []
        items = {i.id: i for i in sess.execute(select(Item).where(Item.org_id == org_id)).scalars().all()}
        locations = {l.id: l for l in sess.execute(select(Location).where(Location.org_id == org_id)).scalars().all()}

        today = ref.date()
        assessments: list[R.RiskAssessment] = []
        for b in batches:
            item = items.get(b.item_id)
            if item is None:
                # Orphaned batch: refuse to score it rather than invent a class.
                logger.warning("batch %s references unknown item %s; skipping", b.id, b.item_id)
                continue
            horizon_end = as_utc(b.expires_at).date()  # type: ignore[union-attr]
            forecast = stored_forecast(
                org_id,
                item_id=b.item_id,
                location_id=b.location_id,
                start=today,
                end=horizon_end,
            )
            history_points = _history_points(sess, org_id, b.item_id, b.location_id)
            assessment = R.assess(
                R.RiskInput(
                    batch_id=b.id,
                    org_id=org_id,
                    item_id=b.item_id,
                    location_id=b.location_id,
                    item_name=item.name,
                    food_class=item.food_class,
                    unit_cost=float(item.unit_cost or 0.0),
                    qty=float(b.qty or 0.0),
                    prepared_at=as_utc(b.received_or_prepared_at),
                    expires_at=as_utc(b.expires_at),
                    storage=b.storage or "ambient",
                    forecast=forecast,
                    model_version=forecast[0]["model_version"] if forecast else "none",
                    history_points=history_points,
                    method=forecast[0]["method"] if forecast else "cold_start",
                ),
                safety=safety,
                now=ref,
            )
            # Enrich with the fields the ladder and validator need.
            loc = locations.get(b.location_id)
            assessment.detail.update(
                {
                    "location_id": b.location_id,
                    "location_name": loc.name if loc else None,
                    "status": assessment.status,
                    "unit_price": float(item.unit_price or 0.0),
                    "unit_weight_kg": float(item.unit_weight_kg or 0.0),
                }
            )
            assessments.append(assessment)

            if persist:
                # Flatten the assessment detail: the risk scalars are already
                # columns, so nesting `to_dict()` inside `detail` would duplicate
                # them and force callers to reach through `detail["detail"]`.
                risk_detail = dict(assessment.detail)
                risk_detail.update(
                    {
                        "status": assessment.status,
                        "batch_id": assessment.batch_id,
                        "item_id": assessment.item_id,
                        "item_name": assessment.item_name,
                        "stock_qty": assessment.stock_qty,
                        "expected_demand": assessment.expected_demand,
                        "expected_unsold": assessment.expected_unsold,
                        "risk": assessment.risk,
                        "urgency_hours": assessment.urgency_hours,
                        "donate_by": iso(assessment.donate_by),
                        "priority": assessment.priority,
                        "value_at_risk": assessment.value_at_risk,
                        "safe_to_donate": assessment.safe_to_donate,
                        "redistributable": assessment.redistributable,
                        "model_version": assessment.model_version,
                    }
                )
                sess.add(
                    WasteRisk(
                        org_id=org_id,
                        batch_id=b.id,
                        computed_at=ref,
                        expected_unsold=assessment.expected_unsold,
                        risk=assessment.risk,
                        urgency_hours=assessment.urgency_hours,
                        donate_by=assessment.donate_by,
                        priority=assessment.priority,
                        detail=risk_detail,
                    )
                )
    return R.rank(assessments)


def _history_points(sess, org_id: str, item_id: str, location_id: str) -> int:
    from sqlalchemy import func

    n = sess.execute(
        select(func.count())
        .select_from(SalesDaily)
        .where(
            SalesDaily.org_id == org_id,
            SalesDaily.item_id == item_id,
            SalesDaily.location_id == location_id,
        )
    ).scalar_one()
    return int(n or 0)


def recurring_unsold_days(org_id: str, item_id: str, location_id: str, *, lookback_days: int = 7) -> int:
    """How many of the last N days the forecast says we over-prepared.

    Feeds the `buy_prepare_less` rung, which is about FUTURE orders, so it is
    computed from a trailing window of persisted forecast rows.
    """
    from sqlalchemy import func

    with session_scope() as sess:
        batches = list_where(sess, Batch, org_id, item_id=item_id, location_id=location_id)
        if not batches:
            return 0
        today = utcnow().date()
        start = today - _dt.timedelta(days=lookback_days)
        rows = stored_forecast(org_id, item_id=item_id, location_id=location_id, start=start, end=today)
        stock = max(float(b.qty or 0.0) for b in batches)
        if stock <= 0:
            return 0
        days = 0
        for r in rows:
            if stock - r["p50"] > 0:
                days += 1
    return days


# --------------------------------------------------------------------------
# Action ladder + recommendation agent
# --------------------------------------------------------------------------
async def recommend(
    org_id: str,
    *,
    batch_id: str | None = None,
    location_id: str | None = None,
    min_risk: float = 0.0,
    limit: int = 5,
    as_of: _dt.datetime | None = None,
    safety: SafetyConfig | None = None,
    persist: bool = True,
) -> dict:
    """Run the agent over the highest-priority at-risk batches.

    Deterministic stages run first (risk + ladder), then the agent chooses, then
    the validator has the last word. Rejected batches are persisted as
    ``status='rejected'`` with their reasons: an audit trail of refusals matters
    more than a tidy success list.
    """
    from app.projects.foodlink_predict import tools as T
    from app.projects.foodlink_predict.agent import new_state, run_recommendation

    safety = safety or get_safety_config()
    ref = as_utc(as_of) or utcnow()
    t0 = time.perf_counter()

    assessments = compute_risk(org_id, batch_id=batch_id, location_id=location_id, persist=True, as_of=ref, safety=safety)
    if not assessments:
        raise NotFound(
            "No inventory batches found for this organization. Upload an inventory CSV or load the synthetic demo dataset."
        )
    targets = R.top_risk(assessments, min_risk=min_risk, limit=limit)

    org_token = T.set_org_context(org_id)
    results: list[dict] = []
    try:
        for assessment in targets:
            recovery = build_recovery_plan(org_id, assessment, ref, safety)
            ladder = _ladder_for(org_id, assessment, ref, safety)
            ctx = {
                "ladder": [c.to_dict() for c in ladder],
                "risk": assessment.to_dict(),
                "recovery_plan": recovery,
                "item": item_payload(org_id, assessment.item_id),
                "preferred_action": next((s["action"] for s in recovery["plan"]), None)
                or next((c.action for c in ladder if c.allowed), None),
                "allowed_actions": [s["action"] for s in recovery["plan"]]
                or [c.action for c in ladder if c.allowed],
            }
            batch_token = T.set_batch_context(ctx)
            try:
                state = new_state(org_id, assessment.batch_id)
                state["as_of"] = iso(ref)
                state["evidence"] = {
                    "item_id": assessment.item_id,
                    "location_id": assessment.location_id,
                    "food_class": assessment.food_class,
                    "storage": assessment.detail.get("storage"),
                    "horizon_days": 7,
                    "risk": assessment.to_dict(),
                    "ladder": ctx["ladder"],
                    "recovery_plan": recovery,
                }
                final = await run_recommendation(state)
            finally:
                T.reset_batch_context(batch_token)

            proposal = final.get("proposal") or {}
            risk_dict = assessment.to_dict()
            steps = recovery.get("plan") or []
            if not steps:
                # No permitted action at all: persist the rejection so the refusal
                # is auditable rather than invisible.
                validation = {"passed": False, "issues": [{"rule": "no_permitted_action", "message": "The action ladder permitted no action for this batch."}]}
                rec = persist_recommendation(
                    org_id,
                    assessment=assessment,
                    proposal=proposal,
                    validation=validation,
                    trace=final.get("tool_calls", []),
                    ref=ref,
                    persist=persist,
                    llm_used=bool(final.get("llm_used")),
                )
                results.append(
                    _result_row(rec, assessment, ctx, proposal, validation, final)
                )
                continue

            # One validated recommendation per recovery step. The agent chose and
            # explained the primary; the remainder steps are deterministic and are
            # re-validated independently, so a rescue can never ride on the
            # approval of an unrelated earlier step.
            for step in steps:
                step_proposal = proposal_for_step(proposal, step)
                if step.get("stage") == "residual":
                    step_proposal["rationale"] = step_rationale(step, risk_dict)
                # Same clock reference as the risk assessment. Using utcnow() here
                # would make the validator disagree with the assessment it is
                # checking - a batch could be scored as safe and then rejected
                # seconds later purely because of elapsed time.
                result_validation = V.validate(step_proposal, now=ref)
                rec = persist_recommendation(
                    org_id,
                    assessment=assessment,
                    proposal=step_proposal,
                    validation={
                        "passed": result_validation.passed,
                        "issues": [i.to_dict() for i in result_validation.issues],
                    },
                    trace=final.get("tool_calls", []),
                    ref=ref,
                    persist=persist,
                    llm_used=bool(final.get("llm_used")) and step.get("stage") == "primary",
                )
                results.append(
                    _result_row(rec, assessment, ctx, step_proposal, result_validation.to_dict(), final)
                )
    finally:
        T.reset_org_context(org_token)

    _record_run(
        org_id,
        stage="recommend",
        request_id="",
        status="ok",
        duration_ms=(time.perf_counter() - t0) * 1000,
        detail={
            "batches_considered": len(assessments),
            "recommendations": len(results),
            "validated": sum(1 for r in results if r["validation_status"] == "passed"),
        },
    )

    return {
        "org_id": org_id,
        "as_of": iso(ref),
        "count": len(results),
        "recommendations": results,
        "validator_passed": [r for r in results if r["validation_status"] == "passed"],
        "validator_rejected": [r for r in results if r["validation_status"] != "passed"],
        "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        "agent": {"graph": "planner->tools->executor->validator->responder", "max_steps": 5, "max_replans": 1},
    }


def _result_row(
    rec: dict,
    assessment: R.RiskAssessment,
    ctx: dict,
    proposal: dict,
    validation: dict,
    final: dict,
) -> dict:
    """Shape one recommendation for the API response."""
    return {
        "recommendation_id": rec["id"],
        "batch_id": assessment.batch_id,
        "item_id": assessment.item_id,
        "item_name": assessment.item_name,
        "action": proposal.get("action"),
        "quantity": proposal.get("quantity"),
        "deadline": proposal.get("deadline"),
        "rationale": proposal.get("rationale"),
        "step": proposal.get("step"),
        "step_stage": proposal.get("step_stage"),
        "validation_status": rec["validation_status"],
        "validation_issues": rec["validation_errors"],
        "status": rec["status"],
        "risk": round(assessment.risk, 4),
        "urgency_hours": round(assessment.urgency_hours, 1),
        "donate_by": iso(assessment.donate_by),
        "expected_unsold": round(assessment.expected_unsold, 2),
        "priority": round(assessment.priority, 3),
        "ladder": ctx.get("ladder", []),
        "recovery_plan": ctx.get("recovery_plan", {}),
        "evidence": proposal.get("evidence"),
        "tool_trace": final.get("tool_calls", []),
        "agent_steps": final.get("steps", []),
        "agent_trace": final.get("trace", []),
        "llm_used": rec.get("llm_used", False),
        "llm_error": final.get("llm_error", ""),
        "llm_provider": _llm_label(),
        "metadata": final.get("metadata", {}),
    }


def _llm_label() -> str:
    try:
        from app.core.config import get_settings

        s = get_settings()
        return f"{s.LLM_PROVIDER}/{s.LLM_MODEL}" + (" (mock - offline)" if s.LLM_PROVIDER == "mock" else "")
    except Exception:
        return "unknown"


def item_payload(org_id: str, item_id: str) -> dict:
    with session_scope() as sess:
        item = get_by_id(sess, Item, item_id, org_id)
        if item is None:
            return {}
        return {
            "item_id": item.id,
            "name": item.name,
            "category": item.category,
            "unit": item.unit,
            "food_class": item.food_class,
            "unit_cost": float(item.unit_cost or 0.0),
            "unit_price": float(item.unit_price or 0.0),
            "unit_weight_kg": float(item.unit_weight_kg or 0.35),
            "shelf_life_hours": float(item.shelf_life_hours or 24.0),
        }


def build_ladder(
    org_id: str,
    assessment: R.RiskAssessment,
    ref: _dt.datetime,
    safety: SafetyConfig,
) -> list[A.ActionCandidate]:
    """Deterministic ladder for one batch, with transfer destinations resolved."""
    return _ladder_for(org_id, assessment, ref, safety)


def build_recovery_plan(
    org_id: str,
    assessment: R.RiskAssessment,
    ref: _dt.datetime,
    safety: SafetyConfig,
    *,
    max_steps: int = 2,
) -> dict:
    """Apply the ladder SEQUENTIALLY over quantity, not once over the batch.

    This is what produces "promote 60, donate the remaining 27". Each accepted
    step consumes part of the stock; the next step is then evaluated against a
    residual re-assessment (see ``risk.assess_residual``), which reuses the same
    demand distribution because the forecast window has not changed.

    ``buy_prepare_less`` is skipped in the residual passes: it acts on future
    orders, not on the stock sitting in front of us.
    """
    plan: list[dict] = []
    current = assessment
    seen_actions: set[str] = set()
    ladder = _ladder_for(org_id, current, ref, safety)

    for step_no in range(max_steps):
        chosen = None
        for cand in ladder:
            if not cand.allowed or cand.action in seen_actions:
                continue
            if cand.action == ACTION_BUY_PREPARE_LESS:
                continue
            if cand.quantity <= 0:
                continue
            chosen = cand
            break
        if chosen is None:
            break

        seen_actions.add(chosen.action)
        entry = chosen.to_dict()
        entry["step"] = step_no + 1
        entry["stage"] = "primary" if step_no == 0 else "residual"
        entry["stock_before"] = round(current.stock_qty, 3)
        entry["risk_before"] = round(current.risk, 4)
        plan.append(entry)

        remaining = max(0.0, current.stock_qty - float(chosen.quantity))
        if remaining <= 0:
            break
        current = R.assess_residual(current, remaining, now=ref)
        ladder = _ladder_for(org_id, current, ref, safety)

    # Surface the recovery-hierarchy advice that does not consume stock.
    advice = [c.to_dict() for c in ladder if c.action == ACTION_BUY_PREPARE_LESS]
    return {
        "plan": plan,
        "advice": advice,
        "residual_qty": round(max(0.0, current.stock_qty), 3),
        "residual_risk": round(current.risk, 4),
        "residual_status": current.status,
        "method": "sequential_ladder_with_residual_reassessment",
    }


def _ladder_for(
    org_id: str,
    assessment: R.RiskAssessment,
    ref: _dt.datetime,
    safety: SafetyConfig,
) -> list[A.ActionCandidate]:
    with session_scope() as sess:
        origin = get_by_id(sess, Location, assessment.location_id, org_id)
        destinations = [
            {"id": l.id, "name": l.name, "lat": l.lat, "lng": l.lng}
            for l in sess.execute(select(Location).where(Location.org_id == org_id)).scalars().all()
            if l.id != assessment.location_id
        ]
        item = get_by_id(sess, Item, assessment.item_id, org_id)
        # Destination headroom = p90 demand at that site (upside case).
        deficit: dict[str, float] = {}
        for dest in destinations:
            rows = stored_forecast(
                org_id,
                item_id=assessment.item_id,
                location_id=dest["id"],
                start=ref.date(),
                end=ref.date() + _dt.timedelta(days=2),
            )
            deficit[dest["id"]] = max((r["p90"] for r in rows), default=0.0)

        class _ItemShim:
            unit_price = float(getattr(item, "unit_price", 0.0) or 0.0) if item else 0.0
            unit_cost = float(getattr(item, "unit_cost", 0.0) or 0.0) if item else 0.0

        class _LocShim:
            id = assessment.location_id
            lat = float(getattr(origin, "lat", 0.0) or 0.0)
            lng = float(getattr(origin, "lng", 0.0) or 0.0)

        recurring = recurring_unsold_days(org_id, assessment.item_id, assessment.location_id)
        return A.rank_actions(
            assessment,
            item=_ItemShim(),
            origin=_LocShim(),
            destinations=destinations,
            deficit_by_location=deficit,
            recurring_unsold_days=recurring,
            safety=safety,
            now=ref,
        )


def persist_recommendation(
    org_id: str,
    *,
    assessment: R.RiskAssessment,
    proposal: dict,
    validation: dict,
    trace: list,
    ref: _dt.datetime,
    persist: bool,
    llm_used: bool,
) -> dict:
    passed = bool(validation.get("passed"))
    rec_id = new_id("rec")
    status = "proposed" if passed else "rejected"
    deadline = proposal.get("deadline")
    rec_row = Recommendation(
        id=rec_id,
        org_id=org_id,
        batch_id=assessment.batch_id,
        action=str(proposal.get("action") or "none"),
        rationale=str(proposal.get("rationale") or ""),
        tool_trace=[
            {"tool": t.get("tool"), "args": t.get("args")} for t in (trace or []) if isinstance(t, dict)
        ],
        status=status,
        quantity=float(proposal.get("quantity") or 0.0),
        deadline=as_utc(deadline) if deadline else None,
        evidence=proposal.get("evidence") or {},
        validation_status="passed" if passed else "rejected",
        validation_errors=validation.get("issues") or [],
        model_version=assessment.model_version,
        created_at=ref,
    )
    if persist:
        with session_scope() as sess:
            sess.add(rec_row)
    return {
        "id": rec_id,
        "status": status,
        "validation_status": rec_row.validation_status,
        "validation_errors": rec_row.validation_errors,
        "llm_used": llm_used,
    }


def _record_run(
    org_id: str,
    *,
    stage: str,
    request_id: str,
    status: str,
    duration_ms: float = 0.0,
    model_version: str = "",
    tool_calls: list | None = None,
    detail: dict | None = None,
) -> None:
    """Observability row. Never stores secrets or prompt text."""
    from app.projects.foodlink_predict.models import RunRecord

    try:
        with session_scope() as sess:
            sess.add(
                RunRecord(
                    id=new_id("run"),
                    org_id=org_id,
                    request_id=request_id or "",
                    stage=stage,
                    model_version=model_version,
                    status=status,
                    duration_ms=round(float(duration_ms), 2),
                    tool_calls=(tool_calls or [])[:50],
                    detail=detail or {},
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not record run: %s", exc)


__all__ = [
    "build_ladder",
    "compute_risk",
    "item_payload",
    "persist_recommendation",
    "recurring_unsold_days",
    "recommend",
    "run_forecast",
    "stored_forecast",
]