"""
RAG service - OPTIONAL. Disabled unless RAG_ENABLED=true.
LlamaIndex integration lazily imported. Falls back to simple keyword search.
"""
import logging
import os
from typing import List, Dict, Optional
from app.core.config import get_settings
from app.core.errors import RAGNotEnabledError

logger = logging.getLogger("hackathon.rag")

class RAGService:
    def __init__(self):
        self.enabled = get_settings().RAG_ENABLED
        self._index = None
        self._documents: List[Dict] = []  # Fallback storage
        logger.info(f"RAG init enabled={self.enabled}")

    def ensure_enabled(self):
        if not self.enabled:
            raise RAGNotEnabledError()

    def _try_llama_index(self):
        try:
            import llama_index
            return True
        except ImportError:
            return False

    async def ingest_text(self, text: str, doc_id: str, metadata: Optional[dict] = None) -> dict:
        """Ingest single text chunk. Works without LlamaIndex (simple store)."""
        self.ensure_enabled()
        entry = {"id": doc_id, "text": text, "metadata": metadata or {}}
        self._documents.append(entry)
        logger.info(f"RAG ingested {doc_id} ({len(text)} chars)")

        # If LlamaIndex available, also index it
        if self._try_llama_index():
            try:
                from llama_index.core import Document, VectorStoreIndex
                from llama_index.core.node_parser import SentenceSplitter
                # Lazy - build simple in-memory index
                docs = [Document(text=d["text"], metadata=d["metadata"]) for d in self._documents]
                splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)
                nodes = splitter.get_nodes_from_documents(docs)
                # Use dummy embedding if openai not configured - keeps offline demo working
                # For prod, configure EMBEDDING_MODEL + OPENAI_API_KEY
                logger.info(f"LlamaIndex would index {len(nodes)} nodes (mock if no embedding key)")
            except Exception as e:
                logger.warning(f"LlamaIndex ingest fallback: {e}")

        return {"doc_id": doc_id, "chunks": 1, "total_docs": len(self._documents)}

    async def ingest_file(self, file_path: str, doc_id: str) -> dict:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        return await self.ingest_text(text, doc_id)

    async def retrieve(self, query: str, top_k: int = 3) -> List[Dict]:
        self.ensure_enabled()
        if not self._documents:
            return []

        if self._try_llama_index():
            try:
                # Attempt real retrieval if configured
                # For now return keyword fallback + note
                pass
            except Exception as e:
                logger.warning(f"RAG retrieval fallback: {e}")

        # Simple keyword fallback - works offline, no embeddings needed
        scored = []
        q_words = set(query.lower().split())
        for doc in self._documents:
            text = doc["text"].lower()
            score = sum(1 for w in q_words if w in text)
            if score > 0:
                scored.append({**doc, "score": score, "source": doc["id"]})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def query(self, question: str, top_k: int = 3) -> Dict:
        """Retrieve + format context for LLM."""
        hits = await self.retrieve(question, top_k)
        context = "\n---\n".join([h["text"][:800] for h in hits])
        sources = [{"id": h["id"], "score": h.get("score", 0), "preview": h["text"][:150]} for h in hits]
        return {"context": context, "sources": sources, "hits": len(hits)}

# Singleton - lazy
_rag: Optional[RAGService] = None
def get_rag() -> RAGService:
    global _rag
    if _rag is None:
        _rag = RAGService()
    return _rag
