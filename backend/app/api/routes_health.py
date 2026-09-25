from fastapi import APIRouter
from app.models.schemas import HealthResponse
from app.core.config import get_settings

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
async def health():
    s = get_settings()
    # Detect if API key present without exposing it
    configured = bool(s.LLM_API_KEY) or s.LLM_PROVIDER == "mock"
    return HealthResponse(
        status="ok",
        version="0.1.0",
        llm_provider=s.LLM_PROVIDER,
        llm_model=s.LLM_MODEL,
        rag_enabled=s.RAG_ENABLED,
        db_enabled=s.SUPABASE_ENABLED,
        llm_configured=configured
    )

@router.get("/health/db")
async def db_health():
    from app.database.service import get_db
    db = get_db()
    return await db.health()

@router.get("/health/rag")
async def rag_health():
    s = get_settings()
    return {"enabled": s.RAG_ENABLED, "provider": s.RAG_PROVIDER if s.RAG_ENABLED else "disabled"}
