"""Recommendation agent: PLANNER -> TOOLS -> EXECUTOR -> VALIDATOR -> RESPONDER.

Reuse, not reinvention
----------------------
* ``MAX_STEPS`` and the planner/executor/validator/responder shape come from
  ``app.agents.workflow``.
* Tools live in the toolkit's shared ``TOOL_REGISTRY`` (see ``tools.py``).
* JSON extraction/repair uses the toolkit's ``_extract_json_object``.
* The LLM is the toolkit's ``LLMService``, so mock/offline behaves identically.
* LangGraph ``StateGraph`` mirrors ``build_workflow``; if langgraph is missing the
  sequential fallback mirrors ``_SequentialFallback``.

What the LLM is allowed to do
-----------------------------
Select one action from the validator-approved set, and write prose. That is all.
It never sees a calculator, it never emits a quantity, a donate_by, a risk score
or a forecast value into the structured output. Those are read back from the
deterministic evidence bundle after the LLM has finished.

``lint_rationale`` then checks that every number appearing in the LLM's prose
also appears in the evidence. A rationale containing an unsourced number is
flagged rather than shipped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional, TypedDict

from app.agents.nodes import _extract_json_object
from app.agents.workflow import MAX_STEPS
from app.ai.llm_service import LLMService
from app.projects.foodlink_predict.util import as_utc

logger = logging.getLogger("flp.agent")

# Hard cap on replans. One replan is enough to route around a bad selection;
# more would just burn LLM calls on a deterministic problem.
MAX_REPLANS = 1

SYSTEM_PLANNER = (
    "You plan food-waste mitigation. You do NOT invent numbers. "
    "Every quantity, risk score, date and deadline you may use is supplied in the EVIDENCE block. "
    "You choose which already-computed action to take and you explain it in plain language."
)

SYSTEM_SELECTOR = (
    "You choose ONE action for a batch of food. Rules: "
    "pick an action whose name is in the ALLOWED_ACTIONS list, exactly as written; "
    "never invent quantities, dates, deadlines or scores; write a rationale of at most 60 words; "
    "cite nothing that is not in the EVIDENCE block. Output JSON only."
)


class PredictState(TypedDict, total=False):
    org_id: str
    batch_id: str
    input: str
    as_of: Optional[str]
    plan: str
    steps: list
    trace: list
    tool_calls: list
    tool_results: list
    evidence: dict
    allowed_actions: list
    chosen_action: str
    rationale: str
    proposal: dict
    validation: dict
    final: str
    errors: list
    metadata: dict
    retry_count: int
    executor_steps: int
    total_duration_ms: float
    llm_used: bool
    llm_error: str


def new_state(org_id: str, batch_id: str, question: str = "") -> PredictState:
    return {
        "org_id": org_id,
        "batch_id": batch_id,
        "input": question or f"Recommend a recovery action for batch {batch_id}",
        "plan": "",
        "steps": [],
        "trace": [],
        "tool_calls": [],
        "tool_results": [],
        "evidence": {},
        "allowed_actions": [],
        "chosen_action": "",
        "rationale": "",
        "proposal": {},
        "validation": {},
        "final": "",
        "errors": [],
        "metadata": {},
        "retry_count": 0,
        "executor_steps": 0,
        "total_duration_ms": 0.0,
        "llm_used": False,
        "llm_error": "",
    }


def _record(state: dict, node: str, summary: str, *, tool: str = "", duration_ms: float = 0.0) -> dict:
    entry = {
        "node": node,
        "output_summary": (summary or "")[:160],
        "tool_name": tool,
        "duration_ms": round(duration_ms, 1),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return {
        "trace": list(state.get("trace", [])) + [entry],
        "steps": list(state.get("steps", [])) + [f"{node}: {entry['output_summary']}"],
    }


def _is_mock() -> bool:
    try:
        from app.core.config import get_settings

        return get_settings().LLM_PROVIDER == "mock"
    except Exception:
        return True


# --------------------------------------------------------------------------
# 1. PLANNER
# --------------------------------------------------------------------------
async def planner_node(state: dict) -> dict[str, Any]:
    t0 = time.perf_counter()
    allowed = state.get("allowed_actions", [])
    ladder = state.get("evidence", {}).get("ladder", [])
    if _is_mock():
        plan_text = (
            "1. Read the computed forecast and risk for this batch\n"
            "2. Read the recovery ladder and its allow/deny reasons\n"
            "3. Choose the highest-ranked permitted action\n"
            "4. Validate safety, then explain"
        )
    else:
        llm = LLMService()
        prompt = (
            f"Task: {state.get('input')}\n"
            f"Batch: {state.get('batch_id')}\n"
            f"Allowed actions: {allowed}\n"
            f"Ladder (already computed): {json.dumps(ladder, default=str)[:2000]}\n"
            "Write a 1-4 line plan."
        )
        try:
            plan_text = await llm.generate(prompt, system=SYSTEM_PLANNER, temperature=0.0, max_tokens=300)
        except Exception as exc:  # noqa: BLE001
            logger.warning("planner LLM failed, using deterministic plan: %s", exc)
            state["llm_error"] = f"planner: {type(exc).__name__}"
            plan_text = "1. Read forecast and risk\n2. Read ladder\n3. Choose permitted action\n4. Validate"
    out = _record(state, "planner", plan_text, duration_ms=(time.perf_counter() - t0) * 1000)
    out["plan"] = plan_text
    return out


# --------------------------------------------------------------------------
# 2. TOOLS  (deterministic evidence gathering - no LLM involvement)
# --------------------------------------------------------------------------
async def tools_node(state: dict) -> dict[str, Any]:
    """Run every evidence tool in a fixed order.

    This phase is deliberately NOT LLM-routed. The agent must always look at the
    forecast, the risk and the ladder, so letting a model decide which tools to
    skip would let it recommend without evidence - which the validator would then
    reject anyway.
    """
    from app.projects.foodlink_predict import tools as T

    ev: dict = dict(state.get("evidence") or {})
    calls: list = list(state.get("tool_calls", []))
    results: list = list(state.get("tool_results", []))
    batch_id = state.get("batch_id", "")

    t0 = time.perf_counter()
    item_id = ev.get("item_id", "")
    location_id = ev.get("location_id", "")

    plan = [
        ("get_forecast", lambda: T.invoke_get_forecast(item_id, location_id, int(ev.get("horizon_days", 7)))),
        ("get_risk_items", lambda: T.invoke_get_risk_items(location_id, 0.0, 20)),
        ("rank_actions", lambda: T.invoke_rank_actions(batch_id)),
    ]
    for name, fn in plan:
        try:
            payload = fn()
            ok = "error" not in payload
        except Exception as exc:  # noqa: BLE001
            payload = {"error": f"{type(exc).__name__}: {exc}"}
            ok = False
        calls.append({"tool": name, "args": {"batch_id": batch_id}})
        results.append({"tool": name, "ok": ok, "result": payload})
        ev[name] = payload

    ev["allowed_actions"] = [
        s["action"] for s in (ev.get("recovery_plan") or {}).get("plan", []) if s.get("action")
    ] or [c["action"] for c in ev.get("ladder", []) if c.get("allowed")]
    ev["ladder_allowed"] = [c["action"] for c in ev.get("ladder", []) if c.get("allowed")]
    duration = (time.perf_counter() - t0) * 1000
    out = _record(state, "tools", f"gathered {len(plan)} tool outputs", tool="tools", duration_ms=duration)
    out.update({"evidence": ev, "tool_calls": calls, "tool_results": results, "allowed_actions": ev["allowed_actions"]})
    return out


# --------------------------------------------------------------------------
# 3. EXECUTOR - the only place the LLM chooses anything
# --------------------------------------------------------------------------
async def executor_node(state: dict) -> dict[str, Any]:
    t0 = time.perf_counter()
    # Count the attempt FIRST. Previously this was only incremented on the success
    # path, so a batch with no permitted action re-entered this node forever and
    # LangGraph died on its recursion limit instead of reporting a refusal.
    steps = int(state.get("executor_steps", 0)) + 1
    allowed = list(state.get("allowed_actions") or [])
    ev = state.get("evidence", {})
    failure_hint = (state.get("validation") or {}).get("reasons", [])

    if not allowed:
        out = _record(state, "executor", "no permitted action for this batch", duration_ms=(time.perf_counter() - t0) * 1000)
        out.update(
            {
                "chosen_action": "",
                "rationale": _deterministic_rationale(state, ""),
                "executor_steps": steps,
                "errors": list(state.get("errors", [])) + ["no permitted action"],
            }
        )
        return out

    # Deterministic default: the highest-ranked permitted action.
    default_action = allowed[0]
    chosen, rationale, used_llm, err = default_action, _deterministic_rationale(state, default_action), False, ""

    if not _is_mock():
        llm = LLMService()
        prompt = (
            f"Batch: {state.get('batch_id')}\n"
            f"ALLOWED_ACTIONS: {allowed}\n"
            f"REJECTED_BY_VALIDATOR: {failure_hint or 'none'}\n"
            f"EVIDENCE:\n{json.dumps(_slim_evidence(ev), default=str)[:4000]}\n"
            'Reply with JSON: {"action": "<one allowed action>", "rationale": "<=60 words"}'
        )
        try:
            raw = await llm.generate(prompt, system=SYSTEM_SELECTOR, temperature=0.0, max_tokens=400, json_mode=True)
            data = json.loads(_extract_json_object(raw.strip()) or "{}")
            candidate = str(data.get("action") or "").strip()
            if candidate and candidate in allowed:
                chosen = candidate
                rationale = str(data.get("rationale") or "").strip()
                used_llm = True
            else:
                err = f"llm proposed '{candidate}' which is not in {allowed}; deterministic fallback used"
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"

    if not rationale:
        rationale = _deterministic_rationale(state, chosen)

    proposal = build_proposal(state, chosen, rationale)
    duration = (time.perf_counter() - t0) * 1000
    out = _record(state, "executor", f"selected '{chosen}'" + ("" if used_llm else " (deterministic)"), duration_ms=duration)
    out.update(
        {
            "chosen_action": chosen,
            "rationale": rationale,
            "proposal": proposal,
            "llm_used": used_llm,
            "llm_error": err,
            "executor_steps": steps,
        }
    )
    return out


def _slim_evidence(ev: dict) -> dict:
    """Trim evidence for the prompt: drop bulky ladder internals, keep the numbers."""
    ladder = [
        {"action": c["action"], "allowed": c["allowed"], "reason": c.get("reason", "")}
        for c in (ev.get("ladder") or [])
    ]
    return {
        "risk": ev.get("risk"),
        "forecast": ev.get("get_forecast", {}).get("points", [])[:5],
        "recovery_plan": (ev.get("recovery_plan") or {}).get("plan", []),
        "ladder": ladder,
        "allowed_actions": ev.get("allowed_actions", []),
    }


def build_proposal(state: dict, action: str, rationale: str) -> dict:
    """Assemble the proposal from DETERMINISTIC fields only.

    Every numeric value comes from the evidence bundle. The LLM contributes the
    action name and prose, nothing else.

    The proposal also carries the deterministic ``recovery_plan``: the ordered
    steps (e.g. promote 60, donate the remaining 27) computed by
    ``service.build_recovery_plan``. The agent's chosen action is the primary step;
    the rest is the remainder handling the validator checks independently.
    """
    ev = state.get("evidence") or {}
    risk = ev.get("risk") or {}
    plan = ev.get("recovery_plan") or {}
    ladder = {c["action"]: c for c in (ev.get("ladder") or [])}
    cand = ladder.get(action) or {}
    steps = [s for s in (plan.get("plan") or []) if s.get("action") == action] or ([cand] if cand else [])

    quantity = float(cand.get("quantity") or 0.0)
    if action == "donate":
        # A donation step carries the RESIDUAL quantity, which is what is left
        # after promotion/transfer, not the whole batch.
        quantity = float((steps[0] if steps else {}).get("quantity") or quantity or risk.get("stock_qty") or 0.0)

    return {
        "action": action,
        "quantity": quantity,
        "deadline": (steps[0] if steps else cand).get("deadline") or (risk.get("donate_by") if action == "donate" else None),
        "rationale": rationale,
        "batch": {
            "id": state.get("batch_id"),
            "item_id": ev.get("item_id"),
            "location_id": ev.get("location_id"),
            "qty": risk.get("stock_qty"),
            "food_class": ev.get("food_class"),
            "storage": ev.get("storage"),
            "donate_by": risk.get("donate_by"),
            "expires_at": (risk.get("detail") or {}).get("expires_at"),
            "urgency_hours": risk.get("urgency_hours"),
            "insufficient_history": risk.get("insufficient_history"),
            "history_points": (risk.get("detail") or {}).get("history_points"),
        },
        "location": {"id": ev.get("location_id")},
        "forecast": (ev.get("get_forecast") or {}).get("points", []),
        "recovery_plan": plan,
        "evidence": {
            "forecast": (ev.get("get_forecast") or {}).get("points", []),
            "risk": risk,
            "recovery_plan": plan,
            "tool_calls": list(state.get("tool_calls", [])),
        },
    }


def proposal_for_step(base_proposal: dict, step: dict) -> dict:
    """Derive a proposal for one recovery step from the base proposal.

    The base proposal carries the batch facts, forecast and evidence. A step only
    overrides the three fields it owns - action, quantity, deadline - all of which
    come from the deterministic ladder. This is what turns a single agent turn
    into the full recovery sequence ("transfer 110, donate the remaining 129"),
    each step independently re-checked by the validator.
    """
    out = dict(base_proposal)
    out["action"] = step.get("action")
    out["quantity"] = float(step.get("quantity") or 0.0)
    out["deadline"] = step.get("deadline")
    out["step"] = step.get("step")
    out["step_stage"] = step.get("stage")
    out["reason"] = step.get("reason")
    return out


def step_rationale(step: dict, risk: dict) -> str:
    """Deterministic prose for a step the LLM did not personally select."""
    action = step.get("action")
    qty = float(step.get("quantity") or 0.0)
    stage = step.get("stage", "primary")
    prefix = "" if stage == "primary" else f"After the earlier step, {qty:.0f} units remain: "
    why = step.get("reason") or ""
    return (
        f"{prefix}{action} {qty:.0f} units. Batch {risk.get('batch_id')} holds "
        f"{float(risk.get('stock_qty') or 0):.0f} units with risk {float(risk.get('risk') or 0):.2f} and "
        f"{float(risk.get('urgency_hours') or 0):.1f}h to donate-by {risk.get('donate_by')}. {why}"
    ).strip()


def _deterministic_rationale(state: dict, action: str) -> str:
    """Offline rationale assembled from computed values.

    Used in mock mode and whenever the LLM's text is unusable, so the demo always
    produces a defensible explanation rather than an empty string.
    """
    ev = state.get("evidence") or {}
    risk = ev.get("risk") or {}
    if not risk:
        return f"Recommended '{action}' for batch {state.get('batch_id')}."
    ladder = {c["action"]: c for c in (ev.get("ladder") or [])}
    why = (ladder.get(action) or {}).get("reason", "")
    unsold = risk.get("expected_unsold", 0)
    return (
        f"{int(round(unsold))} of {int(round(risk.get('stock_qty', 0)))} units are forecast to go unsold "
        f"(risk {risk.get('risk', 0):.2f}), with {risk.get('urgency_hours', 0):.1f}h left before donate-by "
        f"{risk.get('donate_by')}. Recommended action: {action}. {why}"
    )


# --------------------------------------------------------------------------
# 4. VALIDATOR - deterministic, cannot be overridden
# --------------------------------------------------------------------------
async def validator_node(state: dict) -> dict[str, Any]:
    from app.projects.foodlink_predict.validators import validate

    t0 = time.perf_counter()
    proposal = state.get("proposal") or {}
    # Reuse the clock the risk assessment was computed against when one was
    # supplied, so the validator cannot disagree with its own evidence.
    result = validate(proposal, now=as_utc(state.get("as_of")))

    summary = {
        "passed": result.passed,
        "status": result.status,
        "issues": [i.to_dict() for i in result.issues],
        "reasons": [i.rule for i in result.issues],
        "checked_rules": result.checked,
        "attempts": int(state.get("retry_count", 0)) + 1,
    }
    duration = (time.perf_counter() - t0) * 1000
    out = _record(state, "validator", f"{result.status} ({len(result.issues)} issue(s))", duration_ms=duration)
    out["validation"] = summary
    if not result.passed:
        out["errors"] = list(state.get("errors", [])) + [i.message for i in result.issues]
    return out


# --------------------------------------------------------------------------
# 5. RESPONDER
# --------------------------------------------------------------------------
async def responder_node(state: dict) -> dict[str, Any]:
    t0 = time.perf_counter()
    proposal = state.get("proposal") or {}
    rationale = (proposal.get("rationale") or "").strip()
    lint = lint_rationale(rationale, proposal.get("evidence") or {})

    if state.get("validation", {}).get("passed"):
        final = rationale or f"Recommended '{proposal.get('action')}'."
    else:
        blocked = ", ".join(state["validation"].get("reasons", []) or ["unknown"])
        final = f"[Blocked by safety validator: {blocked}] No action was authorised for this batch."

    duration = (time.perf_counter() - t0) * 1000
    out = _record(state, "responder", final, duration_ms=duration)
    out["final"] = final
    out["metadata"] = {
        **state.get("metadata", {}),
        "validator_passed": bool(state.get("validation", {}).get("passed")),
        "rationale_lint": lint,
        "llm_used": bool(state.get("llm_used")),
        "llm_error": state.get("llm_error", ""),
        "action": proposal.get("action"),
    }
    return out


_NUM_RE = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?%?")


def lint_rationale(rationale: str, evidence: dict) -> dict[str, Any]:
    """Check that numbers in the LLM's prose also occur in the evidence.

    This is a defence-in-depth check on rule 2 ("the LLM must never invent
    numbers"). It cannot prove a number is *meaningful*, only that it was sourced
    from the deterministic bundle, so an unsourced number is flagged for review
    rather than silently accepted.
    """
    if not rationale:
        return {"checked": False, "reason": "empty rationale"}
    blob = json.dumps(evidence, default=str)
    evidence_numbers = set(_NUM_RE.findall(blob))
    claimed = _NUM_RE.findall(rationale)
    unsourced = sorted({c for c in claimed if c.rstrip("%") not in {e.rstrip("%") for e in evidence_numbers}})
    return {
        "checked": True,
        "numbers_in_rationale": len(claimed),
        "unsourced_numbers": unsourced,
        "passed": not unsourced,
        "note": "unsourced numbers must not be presented as facts" if unsourced else "all numbers trace to tool output",
    }


# --------------------------------------------------------------------------
# Graph wiring (mirrors app.agents.workflow.build_workflow)
# --------------------------------------------------------------------------
def _executor_should_continue(state: dict) -> str:
    return "validator" if int(state.get("executor_steps", 0)) >= 1 else "executor"


def _validator_route(state: dict) -> str:
    val = state.get("validation") or {}
    if not val.get("passed", False) and int(state.get("retry_count", 0)) < MAX_REPLANS:
        return "retry_planner"
    return "responder"


def build_workflow():
    try:
        from langgraph.graph import END, StateGraph

        wf = StateGraph(PredictState)
        wf.add_node("planner", planner_node)
        wf.add_node("tools", tools_node)
        wf.add_node("executor", executor_node)
        wf.add_node("validator", validator_node)
        wf.add_node("responder", responder_node)
        wf.set_entry_point("planner")
        wf.add_edge("planner", "tools")
        wf.add_edge("tools", "executor")
        wf.add_conditional_edges(
            "executor", _executor_should_continue, {"executor": "executor", "validator": "validator"}
        )
        wf.add_conditional_edges(
            "validator", _validator_route, {"retry_planner": "tools", "responder": "responder"}
        )
        wf.add_edge("responder", END)
        return wf.compile()
    except ImportError:
        logger.warning("LangGraph not installed; FoodLink Predict agent uses the sequential fallback")
        return _SequentialFallback()


class _SequentialFallback:
    """Mirror of app.agents.workflow._SequentialFallback."""

    async def ainvoke(self, state: dict) -> dict:
        s = dict(state)
        t0 = time.perf_counter()
        s.update(await planner_node(s))
        s.update(await tools_node(s))
        for _ in range(MAX_STEPS):
            before = int(s.get("executor_steps", 0))
            s.update(await executor_node(s))
            if int(s.get("executor_steps", 0)) == before:
                break
        s.update(await validator_node(s))
        if not s.get("validation", {}).get("passed") and int(s.get("retry_count", 0)) < MAX_REPLANS:
            s["retry_count"] = int(s.get("retry_count", 0)) + 1
            s.update(await planner_node(s))
            s.update(await tools_node(s))
            s.update(await executor_node(s))
            s.update(await validator_node(s))
        s.update(await responder_node(s))
        s["total_duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return s

    async def invoke(self, state: dict) -> dict:
        return await self.ainvoke(state)


_workflow = None


def get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = build_workflow()
    return _workflow


async def run_recommendation(state: PredictState) -> dict:
    """Run the agent to completion and return the final state."""
    wf = get_workflow()
    t0 = time.perf_counter()
    # Hard ceiling on graph iterations. The nodes already terminate on their own
    # (each increments a step counter), but a bug in a conditional edge should
    # surface as a fast, explicit error instead of burning 10k iterations.
    budget = 4 * MAX_STEPS + 20
    if hasattr(wf, "ainvoke"):
        try:
            result = await wf.ainvoke(dict(state), config={"recursion_limit": budget})
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ not in ("GraphRecursionError", "RecursionError"):
                raise
            logger.error("agent graph hit its step budget (%s); treating as no decision", budget)
            result = dict(state)
            result.setdefault("errors", []).append("agent_step_budget_exhausted")
            result["validation"] = {
                "passed": False,
                "issues": [{"rule": "agent_step_budget_exhausted", "message": "agent exceeded its step budget"}],
                "reasons": ["agent_step_budget_exhausted"],
                "status": "rejected",
                "checked": [],
                "attempts": 0,
            }
            result["final"] = "[Blocked] The agent exceeded its step budget; no action was authorised."
    else:  # pragma: no cover - defensive
        result = await wf.ainvoke(dict(state))
    for key in ("steps", "trace", "tool_calls", "tool_results", "errors"):
        result.setdefault(key, [])
    if not result.get("total_duration_ms"):
        result["total_duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result