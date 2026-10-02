from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from app.agents.workflow import run_workflow, get_workflow
from app.rag.service import get_rag
from app.core.config import get_settings
from app.ai.llm_service import LLMService
import asyncio
import json
import logging
import time

logger = logging.getLogger("hackathon.solve")
router = APIRouter()


def _strip_injection(text: str) -> str:
    # Minimal guard: remove obvious prompt-injection directives from retrieved text.
    bad = ["ignore previous instructions", "ignore all instructions", "system:", "jailbreak"]
    t = text or ""
    low = t.lower()
    for b in bad:
        if b in low:
            t = t.replace(b, "[removed]").replace(b.upper(), "[removed]")
    return t


class SolveRequest(BaseModel):
    query: Optional[str] = Field(None, description="Problem query")
    problem: Optional[str] = Field(None, description="Alias for query")
    context: Optional[str] = None
    use_rag: bool = False
    use_agents: bool = True
    options: Optional[dict] = None
    metadata: Optional[dict] = None

    def get_problem(self) -> str:
        q = self.query or self.problem
        if not q or not q.strip():
            raise HTTPException(status_code=422, detail="query or problem is required")
        if len(q) > 8000:
            raise HTTPException(status_code=422, detail="query too long (max 8000 chars)")
        return q


class SolveResponse(BaseModel):
    success: bool
    answer: str
    sources: List[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    confidence: Optional[float] = None
    reasoning_steps: List[str] = Field(default_factory=list)
    steps: List[dict] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    token_estimate: int = 0


@router.post("/solve", response_model=SolveResponse)
async def solve(req: SolveRequest):
    s = get_settings()
    problem = req.get_problem()
    sources = []
    rag_context = None

    if req.use_rag:
        if not s.RAG_ENABLED:
            raise HTTPException(status_code=400, detail="RAG disabled. Set RAG_ENABLED=true")
        rag = get_rag()
        qr = await rag.query(problem, top_k=3)
        rag_context = _strip_injection(qr["context"])
        sources = qr["sources"]

    if req.use_agents:
        try:
            result = await run_workflow(problem, context=req.context, metadata=req.metadata or req.options, rag_context=rag_context)
            trace = result.get("trace", [])
            return SolveResponse(
                success=True,
                answer=result.get("final") or result.get("draft") or "",
                sources=sources,
                metadata={"workflow": "langgraph", "validator_passed": result.get("metadata", {}).get("validator_passed", True)},
                confidence=None,
                reasoning_steps=result.get("steps", []),
                steps=trace,
                total_duration_ms=float(result.get("total_duration_ms", 0.0)),
                token_estimate=int(result.get("token_estimate", 0)),
            )
        except Exception as e:
            logger.error(f"solve workflow error: {e}")
            llm = LLMService()
            prompt = f"Problem: {problem}\nContext: {req.context or ''}\nRAG: {rag_context or 'None'}"
            answer = await llm.generate(prompt, temperature=0.7, max_tokens=800)
            return SolveResponse(success=True, answer=answer, sources=sources,
                                 metadata={"fallback": str(e)}, confidence=None,
                                 reasoning_steps=["fallback: direct LLM"], steps=[],
                                 total_duration_ms=getattr(llm, "last_latency_ms", 0.0),
                                 token_estimate=getattr(llm, "last_prompt_tokens", 0) + getattr(llm, "last_output_tokens", 0))
    else:
        llm = LLMService()
        prompt = f"Problem: {problem}\nContext: {req.context or ''}"
        answer = await llm.generate(prompt, temperature=0.7, max_tokens=800)
        return SolveResponse(success=True, answer=answer, sources=sources, metadata={"mode": "direct"},
                             confidence=None, reasoning_steps=[],
                             steps=[], total_duration_ms=getattr(llm, "last_latency_ms", 0.0),
                             token_estimate=getattr(llm, "last_prompt_tokens", 0) + getattr(llm, "last_output_tokens", 0))


@router.post("/solve/stream")
async def solve_stream(req: SolveRequest):
    """SSE: emits each agent step as it finishes, then final answer. Consume via fetch+ReadableStream."""
    s = get_settings()
    problem = req.get_problem()
    rag_context = None
    sources: List[dict] = []
    if req.use_rag:
        if not s.RAG_ENABLED:
            raise HTTPException(status_code=400, detail="RAG disabled. Set RAG_ENABLED=true")
        qr = await get_rag().query(problem, top_k=3)
        rag_context = _strip_injection(qr["context"])
        sources = qr["sources"]

    async def gen():
        # Run workflow in background while streaming periodic trace snapshots.
        # Minimal honest SSE: run stepwise via nodes so each step emits as it finishes.
        from app.agents import nodes as N
        state: dict = {"input": problem, "context": req.context, "plan": "", "steps": [], "trace": [],
                       "tool_calls": [], "tool_results": [], "tool_output": None, "rag_context": rag_context,
                       "draft": "", "validation": "", "final": "", "errors": [], "sources": sources,
                       "metadata": req.metadata or req.options or {}, "confidence": None,
                       "retry_count": 0, "executor_steps": 0}
        t0 = time.perf_counter()
        yield f"data: {json.dumps({'type': 'start', 'problem': problem[:120]})}\n\n"
        state.update(await N.planner_node(state))
        yield f"data: {json.dumps({'type': 'step', 'step': state['trace'][-1]})}\n\n"
        for _ in range(5):
            before = len(state.get("tool_calls", []))
            state.update(await N.executor_node(state))
            yield f"data: {json.dumps({'type': 'step', 'step': state['trace'][-1]})}\n\n"
            if len(state.get("tool_calls", [])) == before:
                break
        state.update(await N.validator_node(state))
        yield f"data: {json.dumps({'type': 'step', 'step': state['trace'][-1]})}\n\n"
        if "FAILED" in state.get("validation", ""):
            state["retry_count"] = 1
            state.update(await N.planner_node(state))
            yield f"data: {json.dumps({'type': 'step', 'step': state['trace'][-1]})}\n\n"
            state.update(await N.validator_node(state))
            yield f"data: {json.dumps({'type': 'step', 'step': state['trace'][-1]})}\n\n"
        state.update(await N.responder_node(state))
        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        yield f"data: {json.dumps({'type': 'final', 'answer': state.get('final', ''), 'sources': sources, 'total_duration_ms': total_ms, 'trace': state.get('trace', [])})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
