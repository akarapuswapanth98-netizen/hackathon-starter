"""Agent nodes - planner / executor / validator / responder with structured JSON."""
import json
import logging
import time
from typing import Any, Dict
from pydantic import BaseModel, ValidationError
from app.ai.llm_service import LLMService
from app.ai.prompts import SYSTEM_PLANNER, SYSTEM_REASONER, SYSTEM_VALIDATOR
from app.agents.tools import TOOL_REGISTRY, call_tool, tool_specs
from app.core.config import get_settings

logger = logging.getLogger("hackathon.nodes")


class PlanSchema(BaseModel):
    goal: str
    steps: list[str]
    tools_needed: list[str] = []


class ExecutorDecision(BaseModel):
    tool: str = ""
    args: dict = {}
    done: bool = False
    reason: str = ""


class ValidationSchema(BaseModel):
    verdict: str  # PASS or FAIL
    reason: str = ""


def _summarize(text: str, n: int = 120) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t[:n] + ("..." if len(t) > n else "")


def _is_mock() -> bool:
    try:
        return get_settings().LLM_PROVIDER == "mock"
    except Exception:
        return True


async def _llm_json(llm: LLMService, prompt: str, system: str, schema: type[BaseModel]) -> BaseModel:
    """Call LLM, parse JSON, one safe retry on parse failure."""
    raw = await llm.generate(prompt, system=system + " Return valid JSON only.", temperature=0.2, max_tokens=600)
    text = raw.strip()
    # Strip code fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        # remove leading 'json' marker
        if text.lower().startswith("json"):
            text = text[4:]
    for _ in range(2):
        try:
            data = json.loads(text)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            raw2 = await llm.generate(
                f"Fix this into valid JSON for schema {schema.__name__}:\n{text[:1500]}",
                system="Return valid JSON only.", temperature=0.0, max_tokens=600,
            )
            text = raw2.strip()
    # Fallback: raise to let caller use deterministic default
    raise ValueError(f"Could not parse JSON: {text[:300]}")


def _record(state: dict, node: str, inp: str, out: str, tool_name: str = "", duration_ms: float = 0.0) -> dict:
    entry = {
        "node": node,
        "input_summary": _summarize(inp),
        "output_summary": _summarize(out),
        "tool_name": tool_name,
        "duration_ms": round(duration_ms, 1),
    }
    trace = list(state.get("trace", [])) + [entry]
    steps = list(state.get("steps", [])) + [f"{node}: {_summarize(out, 100)}"]
    return {"trace": trace, "steps": steps}


async def planner_node(state: dict) -> Dict[str, Any]:
    t0 = time.perf_counter()
    problem = state.get("input", "")
    context = state.get("context") or ""
    if _is_mock():
        plan_obj = PlanSchema(
            goal=problem[:200],
            steps=["Understand problem", "Use tools to gather facts", "Draft answer", "Validate"],
            tools_needed=["calculator"] if any(c.isdigit() for c in problem) else [],
        )
        plan_text = f"Goal: {plan_obj.goal}\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan_obj.steps))
    else:
        llm = LLMService()
        try:
            plan_obj = await _llm_json(
                llm,
                f"Problem: {problem}\nContext: {context}\nTools:\n{tool_specs()}",
                SYSTEM_PLANNER, PlanSchema,
            )
            plan_text = json.dumps(plan_obj.model_dump())
        except Exception:
            plan_text = f"1. Understand: {problem[:100]}\n2. Gather facts\n3. Draft\n4. Validate"
    dur = (time.perf_counter() - t0) * 1000
    out = _record(state, "planner", problem, plan_text, "", dur)
    out["plan"] = plan_text
    return out


async def executor_node(state: dict) -> Dict[str, Any]:
    t0 = time.perf_counter()
    n = int(state.get("executor_steps", 0))
    tool_calls = list(state.get("tool_calls", []))
    tool_results = list(state.get("tool_results", []))
    rag_context = state.get("rag_context") or ""
    problem = state.get("input", "")

    if _is_mock():
        # Deterministic: calculator once if numbers, text_search once if RAG, else time once, then done.
        done_names = {c.get("tool") for c in tool_calls}
        if any(c.isdigit() for c in problem) and "calculator" not in done_names:
            # Pull first simple expression from problem or default 2+2.
            import re
            m = re.search(r"[\d][\d\s\+\-\*\/\(\)\.]*[\d\)]", problem)
            expr = m.group(0).strip() if m else "2+2"
            if len(expr) > 40:
                expr = "2+2"
            tool, args = "calculator", {"expression": expr}
        elif rag_context and "text_search" not in done_names:
            tool, args = "text_search", {"query": problem[:100], "top_k": 3}
        elif "get_current_time" not in done_names and not tool_calls:
            tool, args = "get_current_time", {}
        else:
            dur = (time.perf_counter() - t0) * 1000
            out = _record(state, "executor", "no more tools", "done", "", dur)
            out["executor_steps"] = n
            return out
        result = await call_tool(tool, args)
        tool_calls.append({"tool": tool, "args": args})
        tool_results.append({"tool": tool, "result": result[:1000]})
        draft_bits = [state.get("draft", ""), f"[tool {tool}: {result[:400]}]"]
        draft = "\n".join(b for b in draft_bits if b).strip()
        dur = (time.perf_counter() - t0) * 1000
        out = _record(state, "executor", f"{tool} {args}", result, tool, dur)
        out.update({"tool_calls": tool_calls, "tool_results": tool_results,
                    "tool_output": result[:1000], "draft": draft, "executor_steps": n + 1})
        return out

    # Real LLM decides.
    llm = LLMService()
    prompt = (f"Problem: {problem}\nPlan: {state.get('plan','')}\n"
              f"Tools used: {tool_calls}\nObservations: {[r.get('result','')[:300] for r in tool_results]}\n"
              f"Tools:\n{tool_specs()}\nDecide next tool or done=true.")
    try:
        dec = await _llm_json(llm, prompt, "You route tool calls.", ExecutorDecision)
    except Exception:
        dec = ExecutorDecision(done=True, reason="parse-fallback")
    if dec.done or not dec.tool or dec.tool not in TOOL_REGISTRY:
        dur = (time.perf_counter() - t0) * 1000
        out = _record(state, "executor", prompt, "done", "", dur)
        out["executor_steps"] = n
        return out
    result = await call_tool(dec.tool, dec.args or {})
    tool_calls.append({"tool": dec.tool, "args": dec.args or {}})
    tool_results.append({"tool": dec.tool, "result": result[:1000]})
    dur = (time.perf_counter() - t0) * 1000
    out = _record(state, "executor", f"{dec.tool}", result, dec.tool, dur)
    out.update({"tool_calls": tool_calls, "tool_results": tool_results,
                "tool_output": result[:1000],
                "draft": (state.get("draft", "") + f"\n[tool {dec.tool}: {result[:400]}]").strip(),
                "executor_steps": n + 1})
    return out


async def validator_node(state: dict) -> Dict[str, Any]:
    t0 = time.perf_counter()
    draft = state.get("draft", "") or state.get("tool_output", "") or ""
    # If no draft yet, generate one via reasoner LLM (mock-safe).
    if not draft or len(draft.strip()) < 5:
        llm = LLMService()
        prompt = (f"Problem: {state.get('input','')}\nContext: {state.get('context') or 'None'}\n"
                  f"Plan: {state.get('plan','')}\nTools: {state.get('tool_results', [])}\nRAG: {state.get('rag_context') or 'None'}")
        try:
            draft = await llm.generate(prompt, system=SYSTEM_REASONER, temperature=0.7, max_tokens=800)
        except Exception as e:
            draft = f"[Fallback - LLM error: {e}] {state.get('input','')[:300]}"
    if not draft or len(draft.strip()) < 20:
        verdict, reason = "FAIL", "too short"
    else:
        verdict, reason = "PASS", "has content"
    if _is_mock() and "Mock" in draft:
        verdict, reason = "PASS", "mock mode"
    val_text = f"{verdict}: {reason}" if verdict == "FAIL" else f"PASSED ({reason})" if verdict == "PASS" and reason == "mock mode" else f"PASSED: {reason}"
    # Normalize to old contract strings tests rely on.
    if verdict == "PASS" and "mock" not in reason:
        val_text = "PASSED: has content"
    if verdict == "PASS" and reason == "mock mode":
        val_text = "PASSED (mock mode)"
    if verdict == "FAIL":
        val_text = f"FAILED: {reason}"
    dur = (time.perf_counter() - t0) * 1000
    out = _record(state, "validator", draft, val_text, "", dur)
    meta = dict(state.get("metadata", {}))
    meta["validator_passed"] = (verdict == "PASS")
    out.update({"draft": draft, "validation": val_text, "metadata": meta})
    return out


async def responder_node(state: dict) -> Dict[str, Any]:
    t0 = time.perf_counter()
    draft = state.get("draft", "")
    val = state.get("validation", "")
    final = draft.strip()
    if "FAILED" in val:
        final = f"[Needs revision: {val}]\n\n{draft}"
    dur = (time.perf_counter() - t0) * 1000
    out = _record(state, "responder", draft, final, "", dur)
    out["final"] = final
    return out


# Back-compat aliases for old imports.
async def reasoner_node(state: dict) -> Dict[str, Any]:
    return await validator_node(state)


async def tool_node(state: dict) -> Dict[str, Any]:
    return await executor_node(state)


async def formatter_node(state: dict) -> Dict[str, Any]:
    d = (state.get("draft", "") or "").strip()
    return {"final": d, "steps": list(state.get("steps", [])) + ["formatter: formatted"]}


async def final_node(state: dict) -> Dict[str, Any]:
    return await responder_node(state)
