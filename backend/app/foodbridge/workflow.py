"""FoodBridge LangGraph workflow - the six-agent graph with bounded retry.

    coordinator -> restaurant -> shelter -> matching -> logistics -> verification
        |             |           |                        |
      error         error        error          valid -> coordinator_final
                                                  |
                                       retry (retry_count < MATCH_MAX_RETRIES)
                                                  |
                                              matching
                                                  |
                                        exhausted -> coordinator_error

Falls back to a clean sequential runner if langgraph cannot be imported -
the backend must never break because of an optional dependency.
"""
import asyncio
import inspect
import logging
from typing import Optional

from app.core.config import get_settings
from app.foodbridge.agents import (
    coordinator_error_node,
    coordinator_final_node,
    coordinator_node,
    coordinator_router,
    logistics_node,
    matching_node,
    restaurant_node,
    restaurant_router,
    shelter_node,
    shelter_router,
    verification_node,
    verification_router,
)
from app.foodbridge.events import get_event_store
from app.foodbridge.state import FoodBridgeState

logger = logging.getLogger("hackathon.foodbridge")


def build_match_workflow(matching_fn=None):
    """Compile the StateGraph. matching_fn is injectable for retry tests."""
    matching_fn = matching_fn or matching_node
    try:
        from langgraph.graph import END, StateGraph

        graph = StateGraph(FoodBridgeState)
        graph.add_node("coordinator", coordinator_node)
        graph.add_node("restaurant", restaurant_node)
        graph.add_node("shelter", shelter_node)
        graph.add_node("matching", matching_fn)
        graph.add_node("logistics", logistics_node)
        graph.add_node("verification", verification_node)
        graph.add_node("coordinator_final", coordinator_final_node)
        graph.add_node("coordinator_error", coordinator_error_node)

        graph.set_entry_point("coordinator")
        graph.add_conditional_edges(
            "coordinator", coordinator_router,
            {"restaurant": "restaurant", "error": "coordinator_error"},
        )
        graph.add_conditional_edges(
            "restaurant", restaurant_router,
            {"shelter": "shelter", "error": "coordinator_error"},
        )
        graph.add_conditional_edges(
            "shelter", shelter_router,
            {"matching": "matching", "error": "coordinator_error"},
        )
        graph.add_edge("matching", "logistics")
        graph.add_edge("logistics", "verification")
        graph.add_conditional_edges(
            "verification", verification_router,
            {"matching": "matching", "final": "coordinator_final", "error": "coordinator_error"},
        )
        graph.add_edge("coordinator_final", END)
        graph.add_edge("coordinator_error", END)
        compiled = graph.compile()
        logger.info("FoodBridge LangGraph workflow compiled (matching_fn=%s)", matching_fn.__name__)
        return compiled
    except ImportError as e:
        logger.warning("LangGraph unavailable (%s) - using sequential FoodBridge fallback", e)
        return _SequentialFoodBridge(matching_fn=matching_fn)


async def _run_node(fn, state: dict) -> dict:
    out = fn(state)
    if inspect.isawaitable(out):
        out = await out
    return out or {}


class _SequentialFoodBridge:
    """Mirror of the graph for environments without langgraph.

    Retry is bounded by MATCH_MAX_RETRIES just like the LangGraph path -
    at most 1 + MATCH_MAX_RETRIES matching attempts, never a loop.
    """

    def __init__(self, matching_fn=None):
        self.matching_fn = matching_fn or matching_node

    async def ainvoke(self, state: dict) -> dict:
        s = dict(state)
        s.setdefault("events", [])
        s.setdefault("steps", [])
        s.setdefault("retry_count", 0)

        async def apply(fn):
            s.update(await _run_node(fn, s))

        await apply(coordinator_node)
        if coordinator_router(s) == "error":
            await apply(coordinator_error_node)
            return s
        await apply(restaurant_node)
        if restaurant_router(s) == "error":
            await apply(coordinator_error_node)
            return s
        await apply(shelter_node)
        if shelter_router(s) == "error":
            await apply(coordinator_error_node)
            return s

        max_attempts = 1 + max(0, int(get_settings().MATCH_MAX_RETRIES))
        for _ in range(max_attempts):
            await apply(self.matching_fn)
            await apply(logistics_node)
            await apply(verification_node)
            path = verification_router(s)
            if path == "final":
                await apply(coordinator_final_node)
                return s
            if path != "matching":
                break
        await apply(coordinator_error_node)
        return s

    async def invoke(self, state: dict) -> dict:
        return await self.ainvoke(state)


_workflow = None


def get_match_workflow():
    global _workflow
    if _workflow is None:
        _workflow = build_match_workflow()
    return _workflow


async def run_match_workflow(
    initial: FoodBridgeState,
    workflow=None,
    timeout_seconds: Optional[float] = None,
) -> dict:
    """Run the match graph with asyncio.wait_for timeout protection.

    On timeout: status="timeout", events recovered from the event bus.
    """
    settings = get_settings()
    wf = workflow or get_match_workflow()
    timeout = float(timeout_seconds if timeout_seconds is not None else settings.MATCH_TIMEOUT_SECONDS)
    try:
        result = await asyncio.wait_for(wf.ainvoke(dict(initial)), timeout=timeout)
        return dict(result)
    except asyncio.TimeoutError:
        wid = initial.get("workflow_id") or ""
        ev = get_event_store().emit(wid, "coordinator", "failed", f"workflow timed out after {timeout}s")
        out = dict(initial)
        out["events"] = list(initial.get("events") or []) + [ev]
        out["status"] = "timeout"
        out["error"] = {"code": "MATCH_TIMEOUT", "message": f"Match workflow exceeded {timeout}s", "details": []}
        out["summary"] = ""
        out["summary_source"] = "skipped"
        logger.warning("FoodBridge workflow %s timed out after %ss", wid, timeout)
        return out
