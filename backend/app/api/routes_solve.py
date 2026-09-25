from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from app.agents.workflow import run_workflow
from app.rag.service import get_rag
from app.core.config import get_settings
from app.ai.llm_service import LLMService
import logging

logger = logging.getLogger("hackathon.solve")
router = APIRouter()

# Spec-compliant request: query, context, options, but also support 'problem' alias
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
        if not q:
            raise HTTPException(status_code=422, detail="query or problem is required")
        return q

class SolveResponse(BaseModel):
    success: bool
    answer: str
    sources: List[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    confidence: Optional[float] = None
    reasoning_steps: List[str] = Field(default_factory=list)

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
        rag_context = qr["context"]
        sources = qr["sources"]

    # Demo mode: allow mock without failing
    if req.use_agents:
        try:
            result = await run_workflow(problem, context=req.context, metadata=req.metadata or req.options, rag_context=rag_context)
            return SolveResponse(
                success=True,
                answer=result.get("final") or result.get("draft") or "",
                sources=sources,
                metadata={"workflow": "langgraph", "validator_passed": result.get("metadata", {}).get("validator_passed", True)},
                confidence=None,
                reasoning_steps=result.get("steps", [])
            )
        except Exception as e:
            logger.error(f"solve workflow error: {e}")
            # Fallback to direct LLM
            llm = LLMService()
            prompt = f"Problem: {problem}\nContext: {req.context or ''}\nRAG: {rag_context or 'None'}"
            answer = await llm.generate(prompt, temperature=0.7, max_tokens=800)
            return SolveResponse(success=True, answer=answer, sources=sources, metadata={"fallback": str(e)}, confidence=None, reasoning_steps=["fallback: direct LLM"])
    else:
        llm = LLMService()
        prompt = f"Problem: {problem}\nContext: {req.context or ''}"
        answer = await llm.generate(prompt, temperature=0.7, max_tokens=800)
        return SolveResponse(success=True, answer=answer, sources=sources, metadata={"mode": "direct"}, confidence=None)
