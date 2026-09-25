"""RAG ingestion helpers - text extraction, chunking."""
import os
from typing import List

def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> List[str]:
    """Simple char-based chunking - replace with LlamaIndex SentenceSplitter tomorrow if needed."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
        if start < 0: start = 0
    return [c for c in chunks if c.strip()]

def extract_text_from_file(path: str) -> str:
    """Basic extraction - extend for PDF/DOCX tomorrow."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(path)
            return "\n".join([p.extract_text() or "" for p in reader.pages])
        except ImportError:
            raise RuntimeError("pypdf not installed: pip install pypdf")
    elif ext in (".txt", ".md", ".csv"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    else:
        # Fallback try read as text
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
