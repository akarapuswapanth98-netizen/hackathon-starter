"""Project-spec intake: problem statement -> structured ProjectSpec + starter plan.

Uses the shared _llm_json helper (JSON mode, required-keys check). Any LLM
failure falls back to a deterministic heuristic spec so the endpoint never
crashes and mock mode works offline.
"""
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.nodes import _llm_json
from app.agents.tools import TOOL_REGISTRY
from app.ai.llm_service import LLMService

logger = logging.getLogger("hackathon.intake")
router = APIRouter()


class Feature(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1, max_length=200)
    data_needed: str = Field(..., min_length=1, max_length=200,
                             description="Seed/demo data this feature needs, e.g. 'seed file of 10 fake specialists in docs/seed/'")


class ProjectSpec(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    target_user: str = Field(..., min_length=1, max_length=200)
    core_problem: str = Field(..., min_length=1, max_length=1000)
    must_have_features: list[Feature] = Field(..., min_length=3, max_length=3)
    stretch_goals: list[str] = Field(..., min_length=2, max_length=3)
    demo_flow: list[str] = Field(..., min_length=4, max_length=6)
    judging_criteria_map: dict[str, str] = Field(..., min_length=3)
    suggested_tools: list[str] = Field(default_factory=list)
    risks: list[str] = Field(..., min_length=2, max_length=3)


class IntakeRequest(BaseModel):
    problem: str
    criteria: Optional[str] = Field(None, max_length=2000,
                                    description="Judging criteria text; when given, judging_criteria_map must use these criteria")


class IntakeResponse(BaseModel):
    success: bool = True
    spec: ProjectSpec
    fallback: str = "llm"  # llm | partial_repair | heuristic
    fallback_reason: str = "none"  # none | truncated | bad_json | wrong_shape | api_error
    total_duration_ms: float = 0.0


INTAKE_EXAMPLE = {
    "title": "Clinic Triage Helper",
    "target_user": "Rural clinic staff triaging patient messages",
    "core_problem": "Staff cannot quickly tell which patient messages are urgent",
    "must_have_features": [
        {"name": "Message intake", "description": "Paste a patient message, get an urgency label", "data_needed": "seed file of 20 sample patient messages in docs/seed/"},
        {"name": "Urgency badge", "description": "Critical/high/normal badge with reason in the UI", "data_needed": "no seed data (rule output only)"},
        {"name": "RAG answers", "description": "Upload clinic policy docs, cite them in replies", "data_needed": "seed file of 1 clinic policy PDF in docs/seed/"},
    ],
    "stretch_goals": ["Telugu input support", "Voice input for messages"],
    "demo_flow": ["Paste message", "See urgency badge", "Upload policy doc", "Ask a question", "Show cited answer"],
    "judging_criteria_map": {"Innovation": "Rule + LLM hybrid triage", "Execution": "Working demo, no stubs", "Demo clarity": "3-minute message-to-answer flow"},
    "suggested_tools": ["text_search", "get_current_time"],
    "risks": ["Long inputs slow the demo — cap at 8000 chars", "Empty document store makes text_search useless — seed one doc"],
}

_KNOWN_TOOLS = ["calculator", "text_search", "get_current_time", "classify_urgency"]


def _pick_tools(problem: str) -> list[str]:
    """Heuristic tool suggestion using only tools registered in the kit."""
    available = [t for t in _KNOWN_TOOLS if t in TOOL_REGISTRY]
    picked: list[str] = []
    low = problem.lower()
    if any(c.isdigit() for c in problem) and "calculator" in available:
        picked.append("calculator")
    if any(k in low for k in ("clinic", "patient", "urgency", "triage")) and "classify_urgency" in available:
        picked.append("classify_urgency")
    if any(k in low for k in ("doc", "pdf", "policy", "upload", "report", "search", "find")) and "text_search" in available:
        picked.append("text_search")
    if "get_current_time" in available and len(picked) < 2:
        picked.append("get_current_time")
    return picked[:3] or [t for t in ("text_search", "get_current_time") if t in available][:2]


# Honest one-line limits per tool. Features may only claim what these do;
# anything else must name its seed data in data_needed.
_TOOL_CAVEATS = {
    "text_search": "searches ONLY documents previously uploaded via /api/upload (or seeded); empty store = no results",
    "get_current_time": "returns the current UTC time only; no scheduling or lookup",
    "calculator": "evaluates an explicit arithmetic expression string only; does not choose the formula",
    "classify_urgency": "keyword rules only (dry-run demo tool); no ML, no medical advice",
}


def _tool_capabilities() -> str:
    lines = []
    for name in sorted(TOOL_REGISTRY):
        desc = str(TOOL_REGISTRY[name].get("description", ""))
        caveat = _TOOL_CAVEATS.get(name, "as described; no external access")
        lines.append(f"- {name}: {desc} LIMIT: {caveat}.")
    return "\n".join(lines)


def _criteria_keys(criteria: str) -> list[str]:
    """Split free-text criteria into short map keys (deterministic, heuristic path)."""
    parts = [p.strip(" -•\t0123456789.)") for p in criteria.replace(";", "\n").splitlines()]
    parts = [p[:80] for p in parts if len(p) >= 3][:4]
    if len(parts) < 3:
        words = criteria.split()
        parts = [" ".join(words[:8]), "Execution quality", "Demo clarity"][:3]
    return parts[:4]


def heuristic_spec(problem: str, criteria: Optional[str] = None) -> ProjectSpec:
    """Deterministic fallback spec. Always valid, clearly generic."""
    p = " ".join(problem.split())
    title = (p[:57] + "...") if len(p) > 60 else p
    if criteria and criteria.strip():
        keys = _criteria_keys(criteria)
        cmap = {k: "Addressed by the demo flow + agent trace (refine for finals)" for k in keys}
    else:
        cmap = {
            "Innovation": "Agent loop with tools, traceable steps",
            "Execution": "Working mock-mode demo, no stubs",
            "Demo": "3-minute solve -> upload -> RAG answer flow",
        }
    return ProjectSpec(
        title=title,
        target_user="Hackathon end-user (refine after problem reveal)",
        core_problem=p[:1000],
        must_have_features=[
            Feature(name="Problem solver", description="Paste the problem in Home.jsx, get an agent answer with steps",
                    data_needed="no seed data (works on any pasted text)"),
            Feature(name="Document Q&A", description="Upload PDF/TXT via /api/upload, ask with Use RAG on, show sources",
                    data_needed="seed file of 1 sample PDF/TXT in docs/seed/"),
            Feature(name="Live demo timeline", description="Stream agent steps via /api/solve/stream into the UI timeline",
                    data_needed="no seed data (uses live trace)"),
        ],
        stretch_goals=["Local-language input", "Voice input"],
        demo_flow=[
            "Paste the problem statement",
            "Run Solve and show the agent timeline",
            "Upload one supporting document",
            "Ask a document-grounded question",
            "Show sources + copy the result",
        ],
        judging_criteria_map=cmap,
        suggested_tools=_pick_tools(problem),
        risks=[
            "Keep inputs under 8000 chars or the API rejects them",
            "Real-LLM calls take 6-30s — keep demo queries short",
            "Free-tier rate limits apply at shared-IP events",
        ],
    )


@router.post("/intake", response_model=IntakeResponse)
async def intake(req: IntakeRequest):
    problem = (req.problem or "").strip()
    if not problem:
        raise HTTPException(status_code=422, detail="problem is required (non-empty string)")
    if len(req.problem) > 8000:
        raise HTTPException(status_code=422, detail="problem too long (max 8000 chars)")

    t0 = time.perf_counter()
    spec, fallback, reason = await generate_spec(problem, criteria=req.criteria)
    total_ms = round((time.perf_counter() - t0) * 1000, 1)
    logger.info("intake fallback=%s reason=%s", fallback, reason)
    return IntakeResponse(success=True, spec=spec, fallback=fallback,
                          fallback_reason=reason, total_duration_ms=total_ms)


class RepairSchema(BaseModel):
    """Gap-fill reply: only the fields the first call left empty."""

    stretch_goals: list[str] = Field(..., min_length=2, max_length=3)
    judging_criteria_map: dict[str, str] = Field(..., min_length=3)
    risks: list[str] = Field(..., min_length=2, max_length=3)


REPAIR_DEFAULTS = {
    "stretch_goals": ["Local-language input", "Voice input"],
    "judging_criteria_map": {
        "Innovation": "Agent loop with tools, traceable steps",
        "Execution": "Working mock-mode demo, no stubs",
        "Demo": "3-minute solve -> upload -> RAG answer flow",
    },
    "risks": [
        "Keep inputs under 8000 chars or the API rejects them",
        "Real-LLM calls take 6-30s — keep demo queries short",
        "Free-tier rate limits apply at shared-IP events",
    ],
}

_REPAIRABLE = ("stretch_goals", "judging_criteria_map", "risks")


def _core_valid(partial: dict) -> bool:
    """Core fields usable? Only then is a repair (not full heuristic) allowed."""
    try:
        if not str(partial.get("title", "")).strip():
            return False
        feats = partial.get("must_have_features")
        if not isinstance(feats, list) or len(feats) != 3:
            return False
        for f in feats:
            if not isinstance(f, dict) or not str(f.get("name", "")).strip() \
                    or not str(f.get("description", "")).strip() \
                    or not str(f.get("data_needed", "")).strip():
                return False
        flow = partial.get("demo_flow")
        if not isinstance(flow, list) or not (4 <= len(flow) <= 6) \
                or not all(str(s).strip() for s in flow):
            return False
        if not str(partial.get("target_user", "")).strip() or not str(partial.get("core_problem", "")).strip():
            return False
        return True
    except Exception:
        return False


async def _try_repair(llm: LLMService, problem: str, partial: dict) -> Optional[ProjectSpec]:
    """Fill ONLY the missing repairable fields via one small LLM call.

    Returns a validated ProjectSpec, or None if the repair call also fails
    (caller then uses deterministic defaults).
    """
    missing = [k for k in _REPAIRABLE if not partial.get(k)]
    logger.warning("intake partial repair, missing=%s", missing)
    try:
        gap = await _llm_json(
            llm,
            f"Existing spec draft:\n{str(partial)[:1500]}\n\nProblem: {problem[:300]}\n\n"
            f"Provide ONLY these missing fields: {missing}. Keep them consistent with the draft above.",
            "You fill gaps in hackathon project specs.",
            RepairSchema,
            example={k: REPAIR_DEFAULTS[k] for k in missing},
            max_tokens=600,
        )
        merged = dict(partial)
        for k in missing:
            merged[k] = getattr(gap, k)
        return ProjectSpec.model_validate(merged)
    except Exception as e:
        logger.warning("intake repair call failed (%s), using defaults", type(e).__name__)
        return None


async def generate_spec(problem: str, criteria: Optional[str] = None) -> tuple[ProjectSpec, str, str]:
    """Shared spec builder used by the endpoint AND backend/scripts/scaffold.py.

    Returns (spec, fallback, reason). reason is one of
    none | truncated | bad_json | wrong_shape | api_error.
    """
    from app.agents.nodes import LLMJSONError
    crit = (criteria or "").strip()
    llm = LLMService()
    try:
        prompt = (
            f"Problem statement:\n{problem}\n\nScope: must be achievable in 24 hours. "
            f"Exactly 3 must-have features, each demoable live. "
            f"Each feature needs data_needed naming its seed/demo data.\n"
            f"RULE: every must-have feature must directly solve the stated core problem. "
            f"Do NOT add a feature just to use a tool; it is fine to use none of the listed tools. "
            f"Note: RAG over uploaded documents plus an LLM answer can already explain or simplify documents.\n"
            f"Tool capabilities (features may ONLY claim what these do; anything else needs seed data):\n{_tool_capabilities()}"
        )
        if crit:
            prompt += f"\nJudging criteria (judging_criteria_map keys MUST be exactly these):\n{crit[:2000]}"
        spec = await _llm_json(
            llm,
            prompt,
            "You write hackathon project specs.",
            ProjectSpec,
            example=INTAKE_EXAMPLE,
            max_tokens=2000,
        )
        # Guardrail: suggested tools must exist in the kit; merge model picks with
        # heuristic picks so actually-used tools (e.g. calculator) aren't dropped.
        suggested = [t for t in spec.suggested_tools if t in TOOL_REGISTRY]
        for t in _pick_tools(problem):
            if t not in suggested:
                suggested.append(t)
        spec.suggested_tools = suggested[:4]
        return spec, "llm", "none"
    except LLMJSONError as e:
        partial = e.partial if isinstance(e.partial, dict) else None
        if e.reason == "wrong_shape" and partial is not None and _core_valid(partial):
            repaired = await _try_repair(llm, problem, partial)
            if repaired is not None:
                return repaired, "partial_repair", e.reason
            merged = dict(partial)
            for k in _REPAIRABLE:
                if not merged.get(k):
                    merged[k] = REPAIR_DEFAULTS[k]
            return ProjectSpec.model_validate(merged), "partial_repair", e.reason
        logger.warning("intake LLM failed (%s), heuristic fallback", e.reason)
        return heuristic_spec(problem, criteria), "heuristic", e.reason
    except Exception as e:
        logger.warning("intake failed (%s), heuristic fallback: %s", type(e).__name__, e)
        return heuristic_spec(problem, criteria), "heuristic", "api_error"
