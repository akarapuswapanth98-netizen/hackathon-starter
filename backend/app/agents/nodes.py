"""
Modular LangGraph nodes - each is independent, replace/add tomorrow.
Keep nodes small and predictable. No infinite loops.
"""
import logging
from typing import Dict, Any
from app.ai.llm_service import LLMService
from app.ai.prompts import SYSTEM_PLANNER, SYSTEM_REASONER, SYSTEM_VALIDATOR
from app.core.config import get_settings

logger = logging.getLogger("hackathon.nodes")

async def planner_node(state: dict) -> Dict[str, Any]:
    """Decompose problem. Heuristic by default - swap to LLM planner if needed."""
    problem = state["input"]
    context = state.get("context") or ""
    # Simple plan - fast, no token cost. For LLM planner tomorrow, uncomment below:
    # llm = LLMService()
    # plan = await llm.generate(f"Plan for: {problem}\nContext: {context}", system=SYSTEM_PLANNER)
    plan = f"1. Understand: {problem[:100]}...\n2. Context: {context[:60] if context else 'None'}\n3. Reason & generate\n4. Validate"
    logger.info("planner done")
    return {"plan": plan, "steps": state.get("steps", []) + ["planner: plan created"]}

async def reasoner_node(state: dict) -> Dict[str, Any]:
    """Core LLM call. Uses provider-agnostic service."""
    llm = LLMService()
    prompt = f"Problem: {state['input']}\nContext: {state.get('context') or 'None'}\nPlan: {state.get('plan','')}\nRAG: {state.get('rag_context','None')}"
    try:
        draft = await llm.generate(prompt, system=SYSTEM_REASONER, temperature=0.7, max_tokens=800)
    except Exception as e:
        logger.error(f"reasoner failed: {e}")
        draft = f"[Fallback - LLM error: {e}] {state['input'][:300]}"
    return {"draft": draft, "steps": state.get("steps", []) + ["reasoner: draft generated"]}

async def tool_node(state: dict) -> Dict[str, Any]:
    """Optional tool/RAG node - fills rag_context if RAG enabled."""
    # Tomorrow: add calculator, retrieval, API calls here
    # Currently passes through - keeps workflow predictable
    rag = state.get("rag_context")
    if rag:
        tool_out = f"Retrieved: {rag[:200]}"
    else:
        tool_out = "No tool output (RAG disabled or no query)"
    return {"tool_output": tool_out, "steps": state.get("steps", []) + ["tool: checked rag"]}

async def validator_node(state: dict) -> Dict[str, Any]:
    """Lightweight validator - checks structure, not facts."""
    draft = state.get("draft", "")
    if not draft or len(draft.strip()) < 20:
        val = "FAILED: too short"
        passed = False
    elif "Mock" in draft and get_settings().LLM_PROVIDER == "mock":
        val = "PASSED (mock mode)"
        passed = True
    else:
        val = "PASSED: has content"
        passed = True
    logger.info(f"validator: {val}")
    # Optional: LLM critic (costs tokens, disabled by default)
    # llm = LLMService()
    # critique = await llm.generate(f"Check: {draft[:400]}", system=SYSTEM_VALIDATOR, max_tokens=100)
    return {"validation": val, "steps": state.get("steps", []) + [f"validator: {val}"], "metadata": {**state.get("metadata", {}), "validator_passed": passed}}

async def formatter_node(state: dict) -> Dict[str, Any]:
    """Optional formatter - clean output formatting."""
    draft = state.get("draft", "")
    # Tomorrow: tailor formatting to problem (JSON, markdown, etc.)
    final = draft.strip()
    return {"final": final, "steps": state.get("steps", []) + ["formatter: formatted"]}

async def final_node(state: dict) -> Dict[str, Any]:
    """Package final response."""
    draft = state.get("draft", "")
    val = state.get("validation", "")
    final = state.get("final") or draft
    if "FAILED" in val:
        final = f"[Needs revision: {val}]\n\n{draft}"
    return {"final": final, "steps": state.get("steps", []) + ["final: packaged"]}
