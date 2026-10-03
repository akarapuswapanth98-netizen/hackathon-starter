"""FoodLink Predict errors.

Everything surfaces through the toolkit's existing ``AppError`` so the global
handler in app/core/errors.py keeps working and the frontend's
``parseErrorBody`` already understands the shape. No error is ever swallowed:
each helper here exists to give a caller an actionable, machine-readable
failure instead of a stack trace.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.core.errors import AppError


class FLPError(AppError):
    """Base class carrying a stable machine-readable ``flp_code``."""

    flp_code = "FLP_ERROR"

    def __init__(self, message: str, status_code: int = 400, detail: str | None = None, **extra: Any) -> None:
        super().__init__(message=message, status_code=status_code, detail=detail)
        self.extra = extra


class ValidationFailed(FLPError):
    """Incoming data or request did not satisfy the contract.

    Row-level issues matter more than the headline message, and the toolkit's
    global handler only emits ``{error, detail}``. So the first few issues are
    folded into ``detail`` as readable text, which means the starter's existing
    ``parseErrorBody`` on the frontend surfaces them without any change there.
    """

    flp_code = "VALIDATION_ERROR"
    MAX_DETAIL_ISSUES = 8

    def __init__(self, message: str, issues: Iterable[dict] | None = None) -> None:
        issues = [i for i in (issues or []) if i]
        if not issues:
            super().__init__(message=message, status_code=422)
            self.issues = []
            return
        shown = issues[: self.MAX_DETAIL_ISSUES]
        parts = []
        for i in shown:
            if isinstance(i, dict):
                row = i.get("row")
                code = i.get("code", "issue")
                text = i.get("message", "")
                parts.append(f"row {row} [{code}] {text}" if row else f"[{code}] {text}")
            else:
                parts.append(str(i))
        if len(issues) > len(shown):
            parts.append(f"...and {len(issues) - len(shown)} more")
        super().__init__(message=message, status_code=422, detail="; ".join(parts))
        self.issues = issues

    def to_payload(self) -> dict:
        return {"code": self.flp_code, "message": self.message, "detail": self.detail, "issues": self.issues}


class NotFound(FLPError):
    flp_code = "NOT_FOUND"

    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=404)


class Conflict(FLPError):
    flp_code = "CONFLICT"

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message=message, status_code=409, detail=detail)


class Forbidden(FLPError):
    flp_code = "FORBIDDEN"

    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=403)


class SafetyViolation(FLPError):
    """A hard safety gate refused the operation. Never overridable by an LLM."""

    flp_code = "SAFETY_VIOLATION"

    def __init__(self, message: str, rule: str, detail: str | None = None) -> None:
        super().__init__(message=message, status_code=422, detail=detail)
        self.rule = rule

    def to_payload(self) -> dict:
        return {"code": self.flp_code, "message": self.message, "rule": self.rule}


class ColdStart(FLPError):
    """Not enough history to model an item; caller must use the fallback path."""

    flp_code = "COLD_START"

    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=422)


class CapabilityUnavailable(FLPError):
    """An optional dependency or external contract is not configured."""

    flp_code = "CAPABILITY_UNAVAILABLE"

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message=message, status_code=503, detail=detail)


class ExternalUnavailable(FLPError):
    """A downstream system (FoodLink) failed or timed out."""

    flp_code = "EXTERNAL_UNAVAILABLE"

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message=message, status_code=503, detail=detail)


class PersistenceError(FLPError):
    flp_code = "DATABASE_ERROR"

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message=message, status_code=503, detail=detail)