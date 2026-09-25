"""Agent state - shared across LangGraph nodes."""
from typing import TypedDict, List, Optional

class AgentState(TypedDict):
    input: str
    context: Optional[str]
    plan: str
    draft: str
    validation: str
    sources: List[dict]
    final: str
    steps: List[str]
    metadata: dict
    # Extension fields for tomorrow's problem
    tool_output: Optional[str]
    rag_context: Optional[str]
    confidence: Optional[float]
