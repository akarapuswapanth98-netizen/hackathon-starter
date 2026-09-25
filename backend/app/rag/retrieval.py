"""Retrieval helpers - thin wrapper around RAGService for direct use."""
from app.rag.service import get_rag

async def retrieve_context(query: str, top_k: int = 3) -> dict:
    rag = get_rag()
    return await rag.query(query, top_k)
