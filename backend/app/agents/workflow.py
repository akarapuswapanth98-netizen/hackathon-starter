"""LangGraph workflow: planner -> executor loop -> validator -> (retry planner once) -> responder."""
import logging
import time
from typing import Optional
from app.agents.state import AgentState
from app.agents.nodes import planner_node, executor_node, validator_node, responder_node

logger = logging.getLogger("hackathon.workflow")
MAX_STEPS = 5


def _executor_should_continue(state: dict) -> str:
    n = int(state.get("executor_steps", 0))
    calls = state.get("tool_calls", [])
    # Stop at max steps or if last executor step decided done (no new call added twice).
    if n >= MAX_STEPS:
        return "validator"
    # If executor ran but added no new call (done), go to validator.
    # Heuristic: if last trace entry is executor/done, stop.
    trace = state.get("trace", [])
    if trace and trace[-1].get("node") == "executor" and trace[-1].get("output_summary") == "done":
        return "validator"
    # Mock deterministic executor adds at most 2 calls; continue once more to observe done.
    if len(calls) >= 2 and n >= 2:
        # One extra executor pass to emit done, then validator.
        if trace and trace[-1].get("node") == "executor":
            return "validator"
    return "executor"


def _validator_route(state: dict) -> str:
    val = state.get("validation", "")
    retry = int(state.get("retry_count", 0))
    if "FAILED" in val and retry < 1:
        return "retry_planner"
    return "responder"


def build_workflow(max_steps: int = MAX_STEPS):
    try:
        from langgraph.graph import StateGraph, END
        wf = StateGraph(AgentState)
        wf.add_node("planner", planner_node)
        wf.add_node("executor", executor_node)
        wf.add_node("validator", validator_node)
        wf.add_node("responder", responder_node)
        wf.set_entry_point("planner")
        wf.add_edge("planner", "executor")
        wf.add_conditional_edges("executor", _executor_should_continue, {"executor": "executor", "validator": "validator"})
        wf.add_conditional_edges("validator", _validator_route, {"retry_planner": "planner", "responder": "responder"})
        wf.add_edge("responder", END)
        compiled = wf.compile()
        logger.info("LangGraph compiled (agent loop, max_steps=%d)", max_steps)
        return compiled
    except ImportError as e:
        logger.warning(f"LangGraph not installed ({e}), fallback")
        return _SequentialFallback(max_steps)


class _SequentialFallback:
    def __init__(self, max_steps: int = MAX_STEPS):
        self.max_steps = max_steps

    async def ainvoke(self, state: dict):
        s = dict(state)
        s.setdefault("steps", [])
        s.setdefault("trace", [])
        s.setdefault("tool_calls", [])
        s.setdefault("tool_results", [])
        s.setdefault("sources", [])
        s.setdefault("metadata", {})
        s.setdefault("errors", [])
        s.setdefault("retry_count", 0)
        s.setdefault("executor_steps", 0)
        t0 = time.perf_counter()
        # planner
        s.update(await planner_node(s))
        # executor loop
        for _ in range(self.max_steps):
            before = len(s.get("tool_calls", []))
            s.update(await executor_node(s))
            after = len(s.get("tool_calls", []))
            if after == before:
                break  # done
        # validator (+ one retry)
        s.update(await validator_node(s))
        if "FAILED" in s.get("validation", "") and s.get("retry_count", 0) < 1:
            s["retry_count"] = 1
            s.update(await planner_node(s))
            for _ in range(self.max_steps):
                before = len(s.get("tool_calls", []))
                s.update(await executor_node(s))
                if len(s.get("tool_calls", [])) == before:
                    break
            s.update(await validator_node(s))
        s.update(await responder_node(s))
        s["total_duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        # token estimate: input+plan+draft chars // 4
        blob = (s.get("input", "") or "") + (s.get("plan", "") or "") + (s.get("draft", "") or "")
        s["token_estimate"] = max(1, len(blob) // 4)
        return s

    async def invoke(self, state: dict):
        return await self.ainvoke(state)


_workflow = None


def get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = build_workflow()
    return _workflow


async def run_workflow(problem: str, context: Optional[str] = None, metadata: Optional[dict] = None,
                       rag_context: Optional[str] = None) -> dict:
    wf = get_workflow()
    initial: AgentState = {
        "input": problem, "context": context, "plan": "", "steps": [], "trace": [],
        "tool_calls": [], "tool_results": [], "tool_output": None, "rag_context": rag_context,
        "draft": "", "validation": "", "final": "", "errors": [], "sources": [],
        "metadata": metadata or {}, "confidence": None, "retry_count": 0,
        "executor_steps": 0, "total_duration_ms": 0.0, "token_estimate": 0,
    }
    t0 = time.perf_counter()
    if hasattr(wf, "ainvoke"):
        result = await wf.ainvoke(initial)
    else:
        result = await wf.invoke(initial)
    # Ensure compat keys + timing for LangGraph path (fallback already sets them).
    result.setdefault("steps", [])
    result.setdefault("trace", [])
    result.setdefault("tool_calls", [])
    result.setdefault("tool_results", [])
    result.setdefault("metadata", {})
    if "total_duration_ms" not in result or not result["total_duration_ms"]:
        result["total_duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if "token_estimate" not in result or not result["token_estimate"]:
        blob = (result.get("input", "") or "") + (result.get("plan", "") or "") + (result.get("draft", "") or "")
        result["token_estimate"] = max(1, len(blob) // 4)
    return result
