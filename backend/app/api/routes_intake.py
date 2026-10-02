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


class ProjectSpec(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    target_user: str = Field(..., min_length=1, max_length=200)
    core_problem: str = Field(..., min_length=1, max_length=1000)
    must_have_features: list[Feature] = Field(..., min_length=3, max_length=3)
    stretch_goals: list[str] = Field(default_factory=list, max_length=3)
    demo_flow: list[str] = Field(..., min_length=4, max_length=6)
    judging_criteria_map: dict[str, str] = Field(default_factory=dict)
    suggested_tools: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list, max_length=3)


class IntakeRequest(BaseModel):
    problem: str


class IntakeResponse(BaseModel):
    success: bool = True
    spec: ProjectSpec
    fallback: str = "llm"  # llm | heuristic
    total_duration_ms: float = 0.0


INTAKE_EXAMPLE = {
    "title": "Clinic Triage Helper",
    "target_user": "Rural clinic staff triaging patient messages",
    "core_problem": "Staff cannot quickly tell which patient messages are urgent",
    "must_have_features": [
        {"name": "Message intake", "description": "Paste a patient message, get an urgency label"},
        {"name": "Urgency badge", "description": "Critical/high/normal badge with reason in the UI"},
        {"name": "RAG answers", "description": "Upload clinic policy docs, cite them in replies"},
    ],
    "stretch_goals": ["Telugu input support"],
    "demo_flow": ["Paste message", "See urgency badge", "Upload policy doc", "Ask a question", "Show cited answer"],
    "judging_criteria_map": {"Innovation": "Rule + LLM hybrid triage", "Execution": "Working demo, no stubs"},
    "suggested_tools": ["text_search", "get_current_time"],
    "risks": ["Long inputs slow the demo — cap at 8000 chars"],
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


def heuristic_spec(problem: str) -> ProjectSpec:
    """Deterministic fallback spec. Always valid, clearly generic."""
    p = " ".join(problem.split())
    title = (p[:57] + "...") if len(p) > 60 else p
    return ProjectSpec(
        title=title,
        target_user="Hackathon end-user (refine after problem reveal)",
        core_problem=p[:1000],
        must_have_features=[
            Feature(name="Problem solver", description="Paste the problem in Home.jsx, get an agent answer with steps"),
            Feature(name="Document Q&A", description="Upload PDF/TXT via /api/upload, ask with Use RAG on, show sources"),
            Feature(name="Live demo timeline", description="Stream agent steps via /api/solve/stream into the UI timeline"),
        ],
        stretch_goals=["Local-language input"],
        demo_flow=[
            "Paste the problem statement",
            "Run Solve and show the agent timeline",
            "Upload one supporting document",
            "Ask a document-grounded question",
            "Show sources + copy the result",
        ],
        judging_criteria_map={
            "Innovation": "Agent loop with tools, traceable steps",
            "Execution": "Working mock-mode demo, no stubs",
            "Demo": "3-minute solve -> upload -> RAG answer flow",
        },
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
    try:
        llm = LLMService()
        spec = await _llm_json(
            llm,
            f"Problem statement:\n{problem}\n\nScope: must be achievable in 24 hours. "
            f"Exactly 3 must-have features, each demoable live. Prefer these existing tools: {sorted(TOOL_REGISTRY)}.",
            "You write hackathon project specs.",
            ProjectSpec,
            example=INTAKE_EXAMPLE,
        )
        # Guardrail: suggested tools must exist in the kit.
        spec.suggested_tools = [t for t in spec.suggested_tools if t in TOOL_REGISTRY][:4]
        if not spec.suggested_tools:
            spec.suggested_tools = _pick_tools(problem)
        fallback = "llm"
    except Exception as e:
        logger.warning("intake LLM failed, heuristic fallback: %s", e)
        spec = heuristic_spec(problem)
        fallback = "heuristic"
    total_ms = round((time.perf_counter() - t0) * 1000, 1)
    return IntakeResponse(success=True, spec=spec, fallback=fallback, total_duration_ms=total_ms)
