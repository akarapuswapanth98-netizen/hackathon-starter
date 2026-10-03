"""Deterministic demo scenario: the PDF's section 11 story, end to end.

    1. seed labelled synthetic data for a cafeteria
    2. forecast demand (with the seasonal-naive comparison)
    3. score the risk board
    4. run the agent -> validated recommendation
    5. publish a FORECAST listing through the adapter
    6. staff CONFIRMS it -> impact recorded
    7. optionally withdraw a second listing to show false-alarm tracking

Every step returns what actually happened. If a gate refuses, the refusal is
reported as a refusal - the scenario never papers over a validator rejection to
keep the narrative tidy.

Deterministic: same seed + same clock input => same numbers. ``as_of`` can be
pinned, which is what the tests do.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from app.projects.foodlink_predict import impact as I
from app.projects.foodlink_predict import service as S
from app.projects.foodlink_predict import surplus as SURPLUS
from app.projects.foodlink_predict import synthetic
from app.projects.foodlink_predict.config import ACTION_DONATE, get_safety_config
from app.projects.foodlink_predict.db import session_scope
from app.projects.foodlink_predict.errors import FLPError
from app.projects.foodlink_predict.models import (
    Batch,
    CalendarDay,
    Forecast,
    ImpactEvent,
    Item,
    Location,
    Recommendation,
    SalesDaily,
    SurplusListing,
    WasteRisk,
)
from app.projects.foodlink_predict.tenancy import ensure_org_exists
from app.projects.foodlink_predict.util import as_utc, iso, utcnow

# Fixed clock for reproducible narrative output.
DEMO_AS_OF = "2026-10-03T06:00:00Z"


def _pin_as_of(as_of: str | None) -> _dt.datetime:
    if as_of:
        from app.projects.foodlink_predict.util import parse_datetime

        return parse_datetime(as_of, field="as_of")
    # Without an explicit clock, use a fixed hour so the demo is stable-ish.
    return utcnow().replace(hour=6, minute=0, second=0, microsecond=0)


def _reset(org_id: str) -> None:
    with session_scope() as sess:
        for model in (
            ImpactEvent,
            SurplusListing,
            Recommendation,
            WasteRisk,
            Forecast,
            Batch,
            SalesDaily,
            CalendarDay,
            Item,
            Location,
        ):
            sess.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)


async def run_async(
    org_id: str,
    *,
    as_of: str | None = None,
    seed: int = synthetic.DEFAULT_SEED,
    history_days: int = 56,
    confirm: bool = True,
    withdraw_one: bool = True,
    reset: bool = True,
    include_backtest: bool = True,
) -> dict[str, Any]:
    """Execute the whole story. Returns a step-by-step transcript."""
    ref = _pin_as_of(as_of)
    steps: list[dict[str, Any]] = []
    ensure_org_exists(org_id, "Demo Cafeteria", org_type="demo")

    # -- 1. seed -----------------------------------------------------------
    if reset:
        _reset(org_id)
    dataset = synthetic.generate(as_of=ref, history_days=history_days, seed=seed)
    with session_scope() as sess:
        seed_summary = synthetic.load_into_db(sess, org_id, dataset)
    steps.append(
        {
            "n": 1,
            "name": "seed synthetic data",
            "status": "ok",
            "detail": {
                "synthetic": True,
                "tag": synthetic.SYNTHETIC_TAG,
                "seed": seed,
                "sales_rows": seed_summary["sales"]["inserted"],
                "batches": seed_summary["inventory"]["inserted"],
                "calendar_days": seed_summary["calendar"]["inserted"],
                "items": seed_summary["items"]["inserted"],
                "note": seed_summary["notes"],
            },
        }
    )

    # -- 2. forecast -------------------------------------------------------
    try:
        fc = S.run_forecast(org_id, horizon_days=7, as_of=ref, include_backtest=include_backtest)
        steps.append(
            {
                "n": 2,
                "name": "demand forecast",
                "status": "ok",
                "detail": {
                    "model": fc["model"],
                    "model_version": fc["model_version"],
                    "rows_written": fc["rows_written"],
                    "series": fc["series_count"],
                    "cold_start_series": fc["cold_start_series"],
                    "model_error": fc.get("model_error"),
                    "ml_available": fc["model"] != "none",
                    "wape_model": fc["evaluation"].get("model", {}).get("wape"),
                    "wape_baseline": fc["evaluation"].get("baseline", {}).get("wape"),
                    "bias_model": fc["evaluation"].get("model", {}).get("bias"),
                    "improvement": fc["evaluation"].get("improvement_vs_baseline"),
                    "contains_synthetic_data": fc["data_provenance"]["contains_synthetic_data"],
                },
            }
        )
    except FLPError as exc:
        steps.append({"n": 2, "name": "demand forecast", "status": "failed", "error": exc.message})
        return {
            "org_id": org_id,
            "as_of": iso(ref),
            "completed": False,
            "steps": steps,
            "narrative": [f"Stopped at step 2: {exc.message}"],
            "error": exc.message,
        }

    # -- 3. risk board -----------------------------------------------------
    assessments = S.compute_risk(org_id, persist=True, as_of=ref)
    risk_board = [a.to_dict() for a in assessments]
    steps.append(
        {
            "n": 3,
            "name": "waste-risk board",
            "status": "ok",
            "detail": {
                "batches_scored": len(risk_board),
                "high_or_critical": sum(1 for a in risk_board if a["status"] in ("critical", "high")),
                "top": [
                    {
                        "batch_id": a["batch_id"],
                        "item": a["item_name"],
                        "stock": a["stock_qty"],
                        "expected_unsold": a["expected_unsold"],
                        "risk": a["risk"],
                        "urgency_hours": a["urgency_hours"],
                        "donate_by": a["donate_by"],
                        "status": a["status"],
                        "priority": a["priority"],
                    }
                    for a in risk_board[:5]
                ],
            },
        }
    )

    # -- 4. agent + validator ---------------------------------------------
    rec_result = await S.recommend(org_id, min_risk=0.0, limit=3, as_of=ref, persist=True)
    recs = rec_result["recommendations"]
    steps.append(
        {
            "n": 4,
            "name": "recommendation agent + validator",
            "status": "ok",
            "detail": {
                "recommendations": len(recs),
                "validated": len(rec_result["validator_passed"]),
                "rejected": len(rec_result["validator_rejected"]),
                "items": [
                    {
                        "recommendation_id": r["recommendation_id"],
                        "batch_id": r["batch_id"],
                        "action": r["action"],
                        "quantity": r["quantity"],
                        "deadline": r["deadline"],
                        "validation": r["validation_status"],
                        "rationale": r["rationale"],
                        "llm_used": r["llm_used"],
                    }
                    for r in recs
                ],
            },
        }
    )

    # -- 5. forecast listing ------------------------------------------------
    listing: dict[str, Any] | None = None
    donate_recs = [r for r in recs if r["action"] == ACTION_DONATE and r["validation_status"] == "passed"]
    if donate_recs:
        target = donate_recs[0]
        try:
            listing = SURPLUS.create_listing(org_id, batch_id=target["batch_id"], now=ref)
            steps.append(
                {
                    "n": 5,
                    "name": "create FORECAST listing via FoodLink adapter",
                    "status": "ok",
                    "detail": {
                        "listing_id": listing["listing_id"],
                        "status": listing["status"],
                        "confidence": listing["confidence"],
                        "donate_by": listing["donate_by"],
                        "source": listing["source"],
                        "foodlink_mode": (listing.get("foodlink") or {}).get("mode"),
                        "simulated": (listing.get("foodlink") or {}).get("simulated"),
                        "real_foodlink_executed": (listing.get("foodlink") or {}).get("real_foodlink_executed", False),
                        "expected_foodlink_behaviour": (listing.get("foodlink") or {}).get("expected_foodlink_behaviour"),
                    },
                }
            )
        except FLPError as exc:
            steps.append(
                {"n": 5, "name": "create FORECAST listing", "status": "refused", "error": exc.message, "rule": getattr(exc, "rule", None)}
            )
    else:
        steps.append(
            {
                "n": 5,
                "name": "create FORECAST listing",
                "status": "skipped",
                "reason": "No validated donate recommendation. The safety validator did not authorise a donation, so no listing was created.",
            }
        )

    # -- 6. staff confirm + impact ------------------------------------------
    if listing and confirm:
        try:
            confirmed = SURPLUS.confirm_listing(
                org_id, listing_id=listing["listing_id"], confirmed_by="demo.staff", now=ref
            )
            steps.append(
                {
                    "n": 6,
                    "name": "staff CONFIRM listing (FoodLink six-agent flow begins)",
                    "status": "ok",
                    "detail": {
                        "listing_id": confirmed["listing_id"],
                        "status": confirmed["status"],
                        "confidence": confirmed["confidence"],
                        "confirmed_qty": confirmed.get("confirmed_qty"),
                        "impact": confirmed.get("impact"),
                        "note": "FoodLink's detect/match/negotiate/hand off/deliver/verify agents run in the FoodLink system, not here.",
                    },
                }
            )
        except FLPError as exc:
            steps.append({"n": 6, "name": "confirm listing", "status": "refused", "error": exc.message})
    elif listing:
        steps.append({"n": 6, "name": "confirm listing", "status": "skipped", "reason": "confirm=False"})

    # -- 7. second listing + false-alarm withdrawal ------------------------
    # A second forecast listing is published and then withdrawn, which is how the
    # product shows it does not inflate impact when a prediction was wrong.
    second_listing_id: str | None = None
    if withdraw_one and len(donate_recs) > 1:
        try:
            second = SURPLUS.create_listing(org_id, batch_id=donate_recs[1]["batch_id"], now=ref)
            second_listing_id = second["listing_id"]
            steps.append(
                {
                    "n": 7,
                    "name": "publish a second FORECAST listing",
                    "status": "ok",
                    "detail": {
                        "listing_id": second_listing_id,
                        "batch_id": donate_recs[1]["batch_id"],
                        "status": second["status"],
                        "confidence": second["confidence"],
                    },
                }
            )
            wd = SURPLUS.withdraw_listing(
                org_id, listing_id=second_listing_id, reason="sales_caught_up", now=ref
            )
            steps.append(
                {
                    "n": 8,
                    "name": "withdraw it (sales caught up -> false alarm)",
                    "status": "ok",
                    "detail": {
                        "listing_id": wd["listing_id"],
                        "status": wd["status"],
                        "reason": wd.get("withdrawn_reason"),
                        "false_alarm": True,
                        "note": wd.get("note"),
                    },
                }
            )
        except FLPError as exc:
            steps.append({"n": 7, "name": "second listing / withdrawal", "status": "refused", "error": exc.message})
    else:
        reason = "withdraw_one=False" if not withdraw_one else "only one donate recommendation exists"
        steps.append({"n": 7, "name": "false-alarm withdrawal", "status": "skipped", "reason": reason})

    # -- 9. impact + honesty metrics ----------------------------------------
    with session_scope() as sess:
        events = list(sess.query(ImpactEvent).filter(ImpactEvent.org_id == org_id).all())
        agg = I.aggregate(events)
        fa = I.false_alarm_stats(sess, org_id)
    steps.append(
        {
            "n": 9,
            "name": "impact ledger",
            "status": "ok",
            "detail": {
                "totals": agg["totals"],
                "by_action": agg["by_action"],
                "factors": agg["factors"],
                "false_alarm_stats": fa,
            },
        }
    )

    from app.projects.foodlink_predict.adapters import describe

    safety = get_safety_config()
    return {
        "org_id": org_id,
        "as_of": iso(ref),
        "completed": True,
        "steps": steps,
        "narrative": _narrative(steps, risk_board),
        "what_is_real": [
            "Forecast quantiles, WAPE vs seasonal-naive baseline, waste risk, donate-by, action ladder",
            "Validator decisions (including any refusals above)",
            "Impact arithmetic",
            "Listing state machine and adapter contract",
        ],
        "what_is_simulated": [
            "All input data is SYNTHETIC (seeded RNG; see the seed step).",
            "FoodLink receipt is simulated by the demo adapter; real_foodlink_executed=false.",
            "FoodLink's six agents (detect/match/negotiate/hand off/deliver/verify) do not run in this process.",
        ],
        "safety_config": {
            "safe_windows_hours": safety.safe_windows_hours,
            "pickup_lead_time_hours": safety.pickup_lead_time_hours,
        },
        "foodlink": describe(),
    }


def _narrative(steps: list[dict[str, Any]], risk_board: list[dict]) -> list[str]:
    """Plain-language story lines for a demo presenter."""
    lines: list[str] = []
    by_name = {s["name"]: s for s in steps}
    risk = by_name.get("waste-risk board")
    if risk:
        top = risk["detail"]["top"][0] if risk["detail"]["top"] else None
        if top:
            lines.append(
                f"A cafeteria prepared {top['stock']:.0f} {top['item']} meals; the forecast expects "
                f"{top['expected_unsold']:.0f} to go unsold. Risk {top['risk']:.2f}, donate-by {top['donate_by']}."
            )
    fc = by_name.get("demand forecast")
    if fc:
        d = fc["detail"]
        lines.append(
            f"Forecast model WAPE {d['wape_model']} vs seasonal-naive {d['wape_baseline']} on a rolling-origin backtest."
        )
    rec = by_name.get("recommendation agent + validator")
    if rec:
        for r in rec["detail"]["items"]:
            lines.append(
                f"Batch {r['batch_id']}: agent chose '{r['action']}' for {r['quantity']} units - validator {r['validation']}."
            )
    lst = by_name.get("create FORECAST listing via FoodLink adapter")
    if lst and lst["status"] == "ok":
        lines.append(f"Forecast listing {lst['detail']['listing_id']} published (status=forecast, no commitment yet).")
    conf = by_name.get("staff CONFIRM listing (FoodLink six-agent flow begins)")
    if conf and conf["status"] == "ok":
        imp = conf["detail"].get("impact") or {}
        lines.append(
            f"Staff confirmed; impact recorded: {imp.get('kg_saved', 0):.1f} kg, "
            f"{imp.get('meals', 0):.0f} meals, {imp.get('co2e_kg', 0):.1f} kg CO2e."
        )
    wd = by_name.get("withdraw it (sales caught up -> false alarm)")
    if wd and wd["status"] == "ok":
        lines.append("A second listing was withdrawn as a false alarm and logged, not counted as impact.")
    return lines


def run(org_id: str, **kwargs: Any) -> dict[str, Any]:
    """Synchronous wrapper around :func:`run_async`.

    Safe to call from a script or a sync test. When a loop is already running
    (e.g. from inside an async route) it hands the coroutine to a worker thread
    with its own loop rather than raising "asyncio.run() cannot be called from a
    running event loop".
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_async(org_id, **kwargs))

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(run_async(org_id, **kwargs))).result()


__all__ = ["DEMO_AS_OF", "run", "run_async"]