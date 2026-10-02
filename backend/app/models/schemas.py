from pydantic import BaseModel, Field
from typing import Optional, List, Any


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    llm_provider: str
    llm_model: str
    rag_enabled: bool
    db_enabled: bool
    llm_configured: bool


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="User message")
    conversation_id: Optional[str] = None
    use_rag: bool = False
    metadata: Optional[dict] = None


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str
    sources: List[dict] = Field(default_factory=list, description="RAG sources if used")
    meta: Optional[dict] = None


class SolveRequest(BaseModel):
    problem: str = Field(..., min_length=1, max_length=20000, description="Problem statement to solve")
    context: Optional[str] = Field(None, description="Optional extra context or constraints")
    use_rag: bool = False
    use_agents: bool = True
    metadata: Optional[dict] = None


class SolveResponse(BaseModel):
    result: str
    reasoning_steps: List[str] = Field(default_factory=list)
    sources: List[dict] = Field(default_factory=list)
    provider: str
    model: str
    validator_passed: bool = True
    meta: Optional[dict] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    path: Optional[str] = None
