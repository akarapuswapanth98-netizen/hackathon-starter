"""JWT authentication and authorization - optional feature.

Provides:
- JWT token creation and verification
- Role-based access control
- Dependency injection for FastAPI routes
- Optional enable/disable via AUTH_ENABLED setting
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union

from jose import jwt, JWTError  # type: ignore  # Jose for JWT handling

from app.core.config import get_settings

settings = get_settings()


def _require_secret() -> str:
    secret = settings.JWT_SECRET or ""
    if not secret:
        raise RuntimeError("JWT_SECRET is unset. Set JWT_SECRET env var or keep AUTH_ENABLED=false.")
    return secret


def create_access_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a JWT access token.

    Args:
        subject: Token subject (typically user ID or username)
        expires_delta: Optional expiration delta; defaults to JWT_EXPIRE_MINUTES
        extra_claims: Additional claims to include in the token

    Returns:
        Encoded JWT string
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    to_encode = {
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "sub": str(subject),
    }

    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(
        to_encode,
        _require_secret(),
        algorithm=settings.JWT_ALGORITHM,
    )

    return encoded_jwt


def decode_access_token(
    token: str,
    credentials_exception: Any,
) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT access token.

    Args:
        token: JWT token string
        credentials_exception: Exception to raise on failure

    Returns:
        Decoded token payload or None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            _require_secret(),
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError as e:
        print(f"JWT decode error: {e}")
        return None


class AuthUser:
    """Represents an authenticated user with roles."""

    def __init__(self, user_id: str, username: str, roles: list[str] = None):
        self.id = user_id
        self.username = username
        self.roles = roles or []

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role.

        Args:
            role: Role name to check

        Returns:
            True if user has the role
        """
        return role in self.roles

    def has_any_role(self, roles: list[str]) -> bool:
        """Check if user has any of the specified roles.

        Args:
            roles: List of role names to check

        Returns:
            True if user has at least one of the roles
        """
        return any(r in self.roles for r in roles)

    def has_all_roles(self, roles: list[str]) -> bool:
        """Check if user has all of the specified roles.

        Args:
            roles: List of role names to check

        Returns:
            True if user has all of the roles
        """
        return all(r in self.roles for r in roles)


def get_current_user(
    token: str = ...,
) -> AuthUser:
    """Dependency to get the current authenticated user from a JWT token.

    This is meant to be used as a FastAPI dependency.

    Args:
        token: JWT token (injected by FastAPI from Authorization header)

    Returns:
        AuthUser instance if valid, raises AppError if invalid
    """
    from fastapi import HTTPException, Request

    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token, credentials_exception)

    if payload is None:
        raise credentials_exception

    user_id: str = payload.get("sub")
    roles: list[str] = payload.get("roles", [])

    if user_id is None:
        raise credentials_exception

    return AuthUser(user_id=user_id, username=user_id, roles=roles)


def authenticate_user(
    username: str,
    password: str,
    user_db: Any = None,
) -> Optional[AuthUser]:
    """Authenticate a user against a user database.

    Args:
        username: Username to authenticate
        password: Password to check
        user_db: User database/repository object (optional, for custom auth)

    Returns:
        AuthUser if authentication succeeds, None otherwise
    """
    # No hardcoded users. Provide user_db with verify logic or wire your own DB.
    # Auth stays OFF unless AUTH_ENABLED=true + JWT_SECRET set (see app/main.py).
    if user_db is None:
        return None
    verify = getattr(user_db, "verify_user", None)
    if callable(verify):
        return verify(username, password)
    return None


def authorize(
    current_user: AuthUser,
    required_role: str,
) -> AuthUser:
    """Authorize a user for a specific operation based on role.

    Args:
        current_user: The authenticated user
        required_role: Role required to perform the action

    Returns:
        The current user if authorized

    Raises:
        HTTPException: 403 if user doesn't have the required role
    """
    if not current_user.has_role(required_role):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail=f"Operation requires role: {required_role}",
        )

    return current_user


def authorize_any(
    current_user: AuthUser,
    required_roles: list[str],
) -> AuthUser:
    """Authorize a user if they have any of the required roles.

    Args:
        current_user: The authenticated user
        required_roles: List of roles that grant access

    Returns:
        The current user if authorized

    Raises:
        HTTPException: 403 if user doesn't have any of the required roles
    """
    if not current_user.has_any_role(required_roles):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail=f"Operation requires one of these roles: {required_roles}",
        )

    return current_user