"""FoodBridge workflow state - shared across LangGraph nodes.

All nodes are pure (return partial updates); the graph threads this state.
Domain records are stored as plain dicts (model_dump) for easy serialization.
"""
from typing import List, Optional, TypedDict


class FoodBridgeState(TypedDict, total=False):
    workflow_id: str
    surplus: dict                     # FoodSurplus dump
    restaurant: dict                  # Restaurant dump
    shelters: List[dict]              # all shelters in scope
    candidates: List[dict]            # after shelter-agent filtering
    shelter_ids: Optional[List[str]]  # optional explicit shelter subset
    requested_radius_km: float        # radius filter from the match request
    options: dict                     # MatchOptions dump
    hours_remaining: float            # computed by restaurant agent
    ranked: List[dict]                # scored candidate entries (matching agent)
    allocations: List[dict]           # final allocation plan
    unallocated: int                  # meals left over
    logistics: dict                   # delivery batches
    verification: dict                # {passed, issues, grant_retry}
    total_allocated: int              # verified total from verification_node (committed by coordinator_final)
    retry_count: int                  # retries granted so far (bounded by MATCH_MAX_RETRIES)
    events: List[dict]                # AgentEvent dumps for this workflow
    steps: List[str]                  # human-readable trace
    summary: str                      # natural-language summary (coordinator final)
    summary_source: str               # deterministic | llm | llm-fallback | skipped
    status: str                       # running | completed | failed | timeout
    error: Optional[dict]             # {code, message, details}
