"""Authentication routes - optional JWT auth.

When AUTH_ENABLED=true in the environment, these endpoints are available:
- POST /api/auth/login - Login and receive JWT token
- POST /api/auth/refresh - Refresh JWT token
- POST /api/auth/logout - Logout (client-side token discard)
- GET /api/auth/me - Get current user info

All endpoints return structured error responses per the AppError contract
when authentication fails.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from typing import Dict

from app.core.config import get_settings
from app.auth.jwt import create_access_token, authenticate_user, get_current_user, AuthUser

settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Dict[str, str])
async def login(username: str = ..., password: str = ...):
    """Login and receive JWT token.

    Args:
        username: Username
        password: Password

    Returns:
        JWT access token
    """
    user = authenticate_user(username, password)
    if not user:
        from app.core.errors import AppError

        raise AppError(
            "Authentication failed",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Create access token with user roles as claim
    access_token_expires = timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        extra_claims={"roles": user.roles},
        expires_delta=access_token_expires,
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh")
async def refresh_token(token: str = ...):
    """Refresh a JWT access token.

    Args:
        token: Current JWT token

    Returns:
        New access token
    """
    from app.auth.jwt import decode_access_token

    payload = decode_access_token(token, HTTPException(status_code=401, detail="Invalid token"))

    if payload is None:
        raise HTTPException(status_code=401, detail="Could not refresh token")

    # Create new token with same claims
    user_id = payload.get("sub")
    roles = payload.get("roles", [])

    if not user_id:
        raise HTTPException(status_code=401, detail="Could not refresh token")

    access_token_expires = timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    new_token = create_access_token(
        subject=user_id,
        extra_claims={"roles": roles},
        expires_delta=access_token_expires,
    )

    return {"access_token": new_token, "token_type": "bearer"}


@router.post("/logout")
async def logout():
    """Logout endpoint.

    Note: JWT tokens are stateless; logout is handled client-side by discarding the token.
    This endpoint can be used to invalidate tokens server-side if needed.
    """
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me")
async def me(current_user: AuthUser = Depends(get_current_user)):
    """Get current user information.

    Requires valid JWT token in Authorization header.

    Returns:
        User information including roles
    """
    return {
        "id": current_user.id,
        "username": current_user.username,
        "roles": current_user.roles,
    }