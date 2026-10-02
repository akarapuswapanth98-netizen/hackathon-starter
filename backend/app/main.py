"""Hackathon Starter Backend - FastAPI application factory."""

import logging
import time
import uuid
from collections import defaultdict
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.api.routes_health import router as health_router
from app.api.routes_chat import router as chat_router
from app.api.routes_solve import router as solve_router
from app.api.routes_upload import router as upload_router
from app.auth.jwt import create_access_token, get_current_user, authenticate_user, \
    authorize, authorize_any, AuthUser

# Import auth routes conditionally
try:
    from app.api.routes_auth import router as auth_router
    AUTH_ROUTES_AVAILABLE = True
except ImportError:
    AUTH_ROUTES_AVAILABLE = False

logger = logging.getLogger("hackathon")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app instance.
    """
    s = get_settings()
    app = FastAPI(
        title="Hackathon Starter API",
        version="0.1.0",
        description="Provider-agnostic AI/ML hackathon starter - React + FastAPI + LangGraph + RAG optional"
    )

    # CORS - env driven
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    # --- JWT Authentication (optional, env-driven) ---
    auth_enabled = s.AUTH_ENABLED

    if auth_enabled and not (s.JWT_SECRET or "").strip():
        raise RuntimeError("AUTH_ENABLED=true requires JWT_SECRET env var to be set.")

    if auth_enabled and AUTH_ROUTES_AVAILABLE:
        # Auth routes
        app.include_router(auth_router, prefix="/api", tags=["auth"])

    # Routes under /api
    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(chat_router, prefix="/api", tags=["chat"])
    app.include_router(solve_router, prefix="/api", tags=["solve"])
    app.include_router(upload_router, prefix="/api", tags=["upload"])

    @app.get("/")
    async def root():
        return {"message": "Hackathon Starter API running", "docs": "/docs", "health": "/api/health"}

    # Request-ID + structured log + simple rate limit (60/min/IP on solve/chat).
    _hits: dict[str, list[float]] = defaultdict(list)

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        # Rate limit only mutating agent endpoints.
        if request.url.path in ("/api/solve", "/api/solve/stream", "/api/chat") and request.method == "POST":
            ip = request.client.host if request.client else "unknown"
            now = time.time()
            window = [t for t in _hits[ip] if now - t < 60]
            _hits[ip] = window
            if len(window) >= 60:
                return JSONResponse(status_code=429, content={"error": "Rate limited", "detail": "60 requests/min per IP"})
            window.append(now)
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            logger.exception(f"Middleware error: {e}")
            return JSONResponse(status_code=500, content={"error": "Internal error", "detail": str(e)})
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = req_id
        logger.info("req method=%s path=%s status=%s latency_ms=%s req_id=%s",
                    request.method, request.url.path, status_code, latency_ms, req_id)
        return response

    logger.info(f"App created env={s.APP_ENV} llm={s.LLM_PROVIDER}/{s.LLM_MODEL} rag={s.RAG_ENABLED} db={bool(s.DATABASE_URL)} mode={s.APP_MODE}")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)