"""Agent state - shared across LangGraph nodes."""
from typing import TypedDict, List, Optional


class AgentState(TypedDict, total=False):
    input: str
    context: Optional[str]
    plan: str
    steps: List[str]  # human-readable summaries (compat)
    trace: List[dict]  # detailed: {node, input_summary, output_summary, tool_name, duration_ms}
    tool_calls: List[dict]
    tool_results: List[dict]
    tool_output: Optional[str]
    rag_context: Optional[str]
    draft: str
    validation: str
    final: str
    errors: List[str]
    sources: List[dict]
    metadata: dict
    confidence: Optional[float]
    retry_count: int
    executor_steps: int
    total_duration_ms: float
    token_estimate: int
