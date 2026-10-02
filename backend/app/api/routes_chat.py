from fastapi import APIRouter, HTTPException
from app.models.schemas import ChatRequest, ChatResponse
from app.ai.llm_service import LLMService
from app.rag.service import get_rag
from app.core.config import get_settings
import logging

logger = logging.getLogger("hackathon.chat")
router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    s = get_settings()
    # Handle missing API key gracefully - LLMService will fallback to mock or error
    llm = LLMService()
    sources = []
    context = ""
    if req.use_rag:
        if not s.RAG_ENABLED:
            raise HTTPException(status_code=400, detail="RAG disabled. Set RAG_ENABLED=true")
        rag = get_rag()
        qr = await rag.query(req.message, top_k=3)
        context = qr["context"]
        # Strip obvious injection directives from retrieved text.
        for b in ("ignore previous instructions", "ignore all instructions", "jailbreak"):
            context = context.replace(b, "[removed]")
        sources = qr["sources"]

    prompt = req.message
    if context:
        prompt = f"Context:\n{context}\n\nUser: {req.message}\nAnswer with sources."

    system = "You are a helpful hackathon assistant. Be concise and cite sources if provided."
    try:
        reply = await llm.generate(prompt, system=system, temperature=0.7, max_tokens=800)
    except Exception as e:
        logger.error(f"chat LLM error: {e}")
        raise HTTPException(status_code=503, detail=str(e))

    return ChatResponse(reply=reply, provider=llm.provider, model=llm.model, sources=sources, meta={"use_rag": req.use_rag})
