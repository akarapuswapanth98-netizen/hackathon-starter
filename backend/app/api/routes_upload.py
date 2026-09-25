from fastapi import APIRouter, UploadFile, File, HTTPException
from app.core.config import get_settings
from app.rag.service import get_rag
from app.rag.ingestion import chunk_text
from app.vision.service import get_vision
import os, shutil, logging, uuid

logger = logging.getLogger("hackathon.upload")
router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_TEXT = {".txt", ".md", ".csv", ".pdf"}
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_ALL = ALLOWED_TEXT | ALLOWED_IMAGE

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    s = get_settings()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_ALL:
        raise HTTPException(status_code=400, detail=f"Unsupported file type {ext}. Allowed: {ALLOWED_ALL}")

    # Save
    tmp_name = f"{uuid.uuid4().hex}{ext}"
    tmp_path = os.path.join(UPLOAD_DIR, tmp_name)
    with open(tmp_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    result = {"filename": file.filename, "saved_as": tmp_name, "size": os.path.getsize(tmp_path), "ext": ext}

    # If text and RAG enabled -> ingest
    if ext in ALLOWED_TEXT and s.RAG_ENABLED:
        rag = get_rag()
        try:
            from app.rag.ingestion import extract_text_from_file
            text = extract_text_from_file(tmp_path)
            chunks = chunk_text(text)
            for i, ch in enumerate(chunks[:5]):  # limit 5 chunks for demo
                await rag.ingest_text(ch, doc_id=f"{file.filename}#chunk{i}")
            result["rag_ingested"] = len(chunks[:5])
            result["rag_enabled"] = True
        except Exception as e:
            logger.warning(f"RAG ingest failed: {e}")
            result["rag_error"] = str(e)
    elif ext in ALLOWED_IMAGE:
        vision = get_vision()
        analysis = await vision.analyze_image(tmp_path, prompt="Describe image")
        result["vision"] = analysis

    return result
