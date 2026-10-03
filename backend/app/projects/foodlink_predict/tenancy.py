"""Organization scoping.

Multi-tenancy rule for this project: a request never names its own tenant
without proving it. ``resolve_org_id`` derives the scope from the authenticated
token when auth is on, and from the explicit request field otherwise.

Two guarantees:
* When AUTH_ENABLED=true, a body/query org_id that disagrees with the token's
  claim is rejected with 403 - it is never silently honoured.
* In demo mode the org is still explicit in the DB, so the demo's tenant
  filtering is exercised for real rather than bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.projects.foodlink_predict.errors import Forbidden, ValidationFailed

# Demo-only organization. Labelled 'demo' in the type field so seeded rows are
# never mistaken for a real customer.
DEMO_ORG_ID = "org_demo_cafeteria"


@dataclass(frozen=True)
class OrgContext:
    org_id: str
    is_demo: bool
    actor: str
    roles: tuple[str, ...] = ()

    def require(self, expected_org_id: str) -> None:
        """Guard used before touching any row keyed by org_id."""
        if expected_org_id and expected_org_id != self.org_id:
            # Deliberately identical to the not-found message: confirming that a
            # resource exists in another org would be an information leak.
            raise ValidationFailed(f"Resource '{expected_org_id}' not found for this organization")


def _auth_enabled() -> bool:
    try:
        from app.core.config import get_settings

        return bool(get_settings().AUTH_ENABLED)
    except Exception:
        return False


def resolve_org_id(
    requested_org_id: str | None = None,
    *,
    token: str | None = None,
) -> OrgContext:
    """Determine the organization scope for the current request.

    Args:
        requested_org_id: org id supplied in the body/query (optional in demo).
        token: bearer token; required when AUTH_ENABLED=true.
    """
    from app.core.config import get_settings

    s = get_settings()
    is_demo = bool(getattr(s, "DEMO_MODE", True))

    if not _auth_enabled():
        org_id = (requested_org_id or "").strip() or DEMO_ORG_ID
        return OrgContext(org_id=org_id, is_demo=is_demo, actor="anonymous")

    if not token:
        raise Forbidden("Authentication required: missing bearer token")

    from app.auth.jwt import decode_access_token

    payload = decode_access_token(token, None)
    if not payload:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Could not validate credentials")
    subject = str(payload.get("sub") or "")
    claim_org = payload.get("org_id") or payload.get("org")
    roles = payload.get("roles") or []

    if not claim_org:
        # No org claim: the token cannot be trusted to scope a tenant.
        raise Forbidden("Token carries no organization claim; cannot scope request")

    if requested_org_id and requested_org_id != claim_org:
        # Cross-tenant attempt. Refused rather than downgraded.
        raise Forbidden("Requested organization does not match the authenticated organization")

    return OrgContext(
        org_id=str(claim_org),
        is_demo=is_demo,
        actor=subject or "anonymous",
        roles=tuple(roles),
    )


def ensure_org_exists(org_id: str, name: str | None = None, org_type: str = "cafeteria") -> None:
    """Create the org row on demand so an org-scoped write always has a parent."""
    from app.projects.foodlink_predict.db import get_by_id, session_scope
    from app.projects.foodlink_predict.models import Organization

    with session_scope() as sess:
        if get_by_id(sess, Organization, org_id, org_id) is not None:
            return
        sess.add(
            Organization(
                id=org_id,
                name=name or org_id,
                type=org_type,
                timezone="UTC",
            )
        )


def org_scoped_ids(sess, model, org_id: str) -> set[str]:
    """Every id of `model` visible to org_id. Used to prove isolation in tests."""
    from sqlalchemy import select

    return set(sess.execute(select(model.id).where(model.org_id == org_id)).scalars().all())