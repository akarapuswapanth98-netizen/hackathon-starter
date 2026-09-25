import logging
from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("hackathon")


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 500, detail: str | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class LLMNotConfiguredError(AppError):
    def __init__(self, provider: str):
        super().__init__(
            message=f"LLM provider '{provider}' not configured. Set LLM_API_KEY or {provider.upper()}_API_KEY in .env",
            status_code=503,
            detail="Missing API key"
        )


class RAGNotEnabledError(AppError):
    def __init__(self):
        super().__init__(message="RAG is disabled. Set RAG_ENABLED=true in .env", status_code=400)


async def app_error_handler(request: Request, exc: AppError):
    logger.error(f"AppError {exc.status_code}: {exc.message} | detail={exc.detail} | path={request.url.path}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "detail": exc.detail, "path": str(request.url.path)}
    )


async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error at {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc) if logger.level <= 10 else "Check backend logs"}
    )
