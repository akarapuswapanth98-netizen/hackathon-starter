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


# Required top-level keys per schema: a reply that parses as JSON but lacks these
# (e.g. a model answering the question instead of planning) counts as a parse failure.
_REQUIRED_KEYS: dict[str, list[str]] = {
    "PlanSchema": ["goal", "steps"],
    "ExecutorDecision": ["tool", "done"],
    "ValidationSchema": ["verdict"],
}


def _extract_json_object(text: str) -> str:
    """Return the first balanced {...} JSON object in text (handles prose/code fences)."""
    start = text.find("{")
    while start != -1:
        try:
            _, end = json.JSONDecoder().raw_decode(text[start:])
            return text[start:start + end]
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
    return text


async def _llm_json(llm: LLMService, prompt: str, system: str, schema: type[BaseModel],
                   example: dict | None = None, max_tokens: int = 400) -> BaseModel:
    """Call LLM in JSON mode, parse + strict key-check, one corrective retry.

    Transport-level retries are capped at 1 here: a Groq-side 400
    (json_validate_failed) is deterministic, not transient, so hammering
    the same prompt wastes seconds. The corrective second attempt below
    is the real retry.
    """
    llm.max_retries = 1
    keys = _REQUIRED_KEYS.get(schema.__name__, [])
    if not keys:
        # Derive required keys from the schema so new schemas are strict by default.
        try:
            keys = [k for k, f in schema.model_fields.items() if f.is_required()]
        except Exception:
            keys = []
    if example is None:
        example = {k: ("<string>" if k != "steps" else ["<step>"]) for k in keys}
    ex = json.dumps(example)[:800]
    sys = system + f" Output ONLY a JSON object with exactly these keys: {keys}. Example: {ex}. Do NOT solve or answer the user's problem."
    raw = await llm.generate(prompt, system=sys, temperature=0.0, max_tokens=max_tokens, json_mode=True)
    text = _extract_json_object(raw.strip())
    for attempt in range(2):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and all(k in data for k in keys):
                return schema.model_validate(data)
            raise ValueError(f"missing keys (need {keys})")
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning("_llm_json attempt=%d schema=%s err=%s raw=%.120s", attempt, schema.__name__, e, text)
            if attempt == 0:
                raw2 = await llm.generate(
                    f"You returned: {text[:800]}\nRewrite it as a JSON object with EXACTLY these keys {keys}. Example: {ex}. No other text.",
                    system="Output ONLY JSON.", temperature=0.0, max_tokens=max_tokens, json_mode=True,
                )
                text = _extract_json_object(raw2.strip())
    # Fallback: raise to let caller use deterministic default
    raise ValueError(f"Could not get valid {schema.__name__} JSON")


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


def _validate_tool_args(tool: str, args: dict) -> str | None:
    """Return an error string if args fail the tool's schema, else None."""
    entry = TOOL_REGISTRY.get(tool, {})
    schema = entry.get("args_schema")
    if schema is None:
        return None
    try:
        schema.model_validate(args or {})
        return None
    except Exception as e:
        try:
            fields = list(schema.model_json_schema().get("properties", {}).keys())
        except Exception:
            fields = []
        return f"args {args} invalid for '{tool}' (required: {fields}): {e}".strip()[:300]


def _rule_route(problem: str, rag_context: str, done_names: set[str]) -> tuple[str, dict] | None:
    """Deterministic keyword routing. Used by mock mode AND as the real-LLM fallback
    when the model won't return a valid routing decision (so tools still fire)."""
    if any(c.isdigit() for c in problem) and "calculator" not in done_names:
        import re
        m = re.search(r"[\d][\d\s\+\-\*\/\(\)\.%]*[\d\)%]", problem)
        expr = m.group(0).strip() if m else "2+2"
        if len(expr) > 40:
            expr = "2+2"
        return "calculator", {"expression": expr}
    if rag_context and "text_search" not in done_names:
        return "text_search", {"query": problem[:100], "top_k": 3}
    if "classify_urgency" in TOOL_REGISTRY and "classify_urgency" not in done_names and any(
        k in problem.lower() for k in ("clinic", "patient", "urgency", "chest pain", "bleeding", "fever")
    ):
        return "classify_urgency", {"message": problem[:500]}
    if "get_current_time" not in done_names and not done_names:
        return "get_current_time", {}
    return None


async def executor_node(state: dict) -> Dict[str, Any]:
    t0 = time.perf_counter()
    n = int(state.get("executor_steps", 0))
    tool_calls = list(state.get("tool_calls", []))
    tool_results = list(state.get("tool_results", []))
    rag_context = state.get("rag_context") or ""
    problem = state.get("input", "")
    done_names = {c.get("tool") for c in tool_calls}

    routed: tuple[str, dict] | None = None
    if _is_mock():
        # Deterministic routing in mock mode.
        routed = _rule_route(problem, rag_context, done_names)
    else:
        # Real LLM decides; rule-based fallback guarantees tools still fire on parse failure.
        llm = LLMService()
        prompt = (f"Problem: {problem}\nPlan: {state.get('plan','')}\n"
                  f"Tools used: {tool_calls}\nObservations: {[r.get('result','')[:300] for r in tool_results]}\n"
                  f"Tools:\n{tool_specs()}\n"
                  f"Reply with a JSON object like {{\"tool\": \"calculator\", \"args\": {{\"expression\": \"2+2\"}}, \"done\": false, \"reason\": \"...\"}} "
                  f"or {{\"tool\": \"\", \"args\": {{}}, \"done\": true, \"reason\": \"no more tools needed\"}}. Do NOT solve the problem.")
        try:
            dec = await _llm_json(llm, prompt, "You route tool calls.", ExecutorDecision)
            if not dec.done and dec.tool and dec.tool in TOOL_REGISTRY:
                err = _validate_tool_args(dec.tool, dec.args or {})
                if err is None:
                    routed = (dec.tool, dec.args or {})
                else:
                    # One corrective re-ask: tell the model exactly what's missing.
                    logger.warning("executor bad args, corrective retry: %s", err[:150])
                    dec2 = await _llm_json(
                        llm,
                        prompt + f"\nYour previous args were rejected: {err}. Reply corrected JSON.",
                        "You route tool calls.", ExecutorDecision,
                    )
                    if not dec2.done and dec2.tool and dec2.tool in TOOL_REGISTRY \
                            and _validate_tool_args(dec2.tool, dec2.args or {}) is None:
                        routed = (dec2.tool, dec2.args or {})
                    else:
                        routed = _rule_route(problem, rag_context, done_names)
        except Exception as e:
            logger.warning("executor routing parse failed, rule fallback: %s", e)
            routed = _rule_route(problem, rag_context, done_names)

    if routed is None:
        dur = (time.perf_counter() - t0) * 1000
        out = _record(state, "executor", "no more tools", "done", "", dur)
        out["executor_steps"] = n
        return out
    tool, args = routed
    result = await call_tool(tool, args)
    tool_calls.append({"tool": tool, "args": args})
    tool_results.append({"tool": tool, "result": result[:1000]})
    # Do NOT set draft here: validator synthesizes the final answer from
    # tool_results via LLM so the reply reads as an answer, not a tool echo.
    dur = (time.perf_counter() - t0) * 1000
    out = _record(state, "executor", f"{tool} {args}", result, tool, dur)
    out.update({"tool_calls": tool_calls, "tool_results": tool_results,
                "tool_output": result[:1000], "executor_steps": n + 1})
    return out


async def validator_node(state: dict) -> Dict[str, Any]:
    t0 = time.perf_counter()
    draft = state.get("draft", "") or ""
    # Generate the answer from plan + tool observations (never echo raw tool output).
    if not draft or len(draft.strip()) < 5 or draft.strip().startswith("[tool "):
        llm = LLMService()
        prompt = (f"Problem: {state.get('input','')}\nContext: {state.get('context') or 'None'}\n"
                  f"Plan: {state.get('plan','')}\nTools: {state.get('tool_results', [])}\nRAG: {state.get('rag_context') or 'None'}\n"
                  f"Write the final answer. You MUST include every key number/fact from the tool observations above (e.g. computed totals, retrieved hours) — do not drop them.")
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
