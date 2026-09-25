"""
LangGraph workflow - INPUT -> PLANNER -> REASONER -> TOOL/RAG -> VALIDATOR -> FINAL
Modular nodes from nodes.py, state from state.py.
Falls back to sequential if langgraph not installed.
"""
import logging
from typing import Optional
from app.agents.state import AgentState
from app.agents.nodes import planner_node, reasoner_node, tool_node, validator_node, final_node, formatter_node

logger = logging.getLogger("hackathon.workflow")

def build_workflow(include_tool: bool = False, include_formatter: bool = False):
    try:
        from langgraph.graph import StateGraph, END
        workflow = StateGraph(AgentState)
        workflow.add_node("planner", planner_node)
        workflow.add_node("reasoner", reasoner_node)
        workflow.add_node("validator", validator_node)
        workflow.add_node("final", final_node)
        if include_tool:
            workflow.add_node("tool", tool_node)
        if include_formatter:
            workflow.add_node("formatter", formatter_node)

        workflow.set_entry_point("planner")
        if include_tool:
            workflow.add_edge("planner", "reasoner")
            workflow.add_edge("reasoner", "tool")
            workflow.add_edge("tool", "validator")
        else:
            workflow.add_edge("planner", "reasoner")
            workflow.add_edge("reasoner", "validator")

        if include_formatter:
            workflow.add_edge("validator", "formatter")
            workflow.add_edge("formatter", "final")
        else:
            workflow.add_edge("validator", "final")
        workflow.add_edge("final", END)
        compiled = workflow.compile()
        logger.info(f"LangGraph compiled (tool={include_tool}, formatter={include_formatter})")
        return compiled
    except ImportError as e:
        logger.warning(f"LangGraph not installed ({e}), fallback")
        return _SequentialFallback(include_tool, include_formatter)

class _SequentialFallback:
    def __init__(self, include_tool=False, include_formatter=False):
        self.include_tool = include_tool
        self.include_formatter = include_formatter
    async def ainvoke(self, state: dict):
        s = dict(state)
        s.setdefault("steps", []); s.setdefault("sources", []); s.setdefault("metadata", {})
        seq = [planner_node, reasoner_node]
        if self.include_tool: seq.append(tool_node)
        seq.append(validator_node)
        if self.include_formatter: seq.append(formatter_node)
        seq.append(final_node)
        for node in seq:
            update = await node(s)
            s.update(update)
        return s
    async def invoke(self, state: dict):
        return await self.ainvoke(state)

_workflow = None
_workflow_with_tool = None

def get_workflow(include_tool: bool = False):
    global _workflow, _workflow_with_tool
    if include_tool:
        if _workflow_with_tool is None:
            _workflow_with_tool = build_workflow(include_tool=True)
        return _workflow_with_tool
    if _workflow is None:
        _workflow = build_workflow(include_tool=False)
    return _workflow

async def run_workflow(problem: str, context: Optional[str] = None, metadata: Optional[dict] = None, rag_context: Optional[str] = None) -> dict:
    wf = get_workflow(include_tool=bool(rag_context))
    initial: AgentState = {
        "input": problem,
        "context": context,
        "plan": "",
        "draft": "",
        "validation": "",
        "sources": [],
        "final": "",
        "steps": [],
        "metadata": metadata or {},
        "tool_output": None,
        "rag_context": rag_context,
        "confidence": None,
    }
    if hasattr(wf, "ainvoke"):
        result = await wf.ainvoke(initial)
    else:
        result = await wf.invoke(initial)
    return result
