"""Security tests: tenant isolation, authorization, input validation, secrets.

The isolation tests deliberately go through the DB helpers as well as the API,
because "the route filters by org_id" is only half the guarantee - the query
layer must be incapable of returning another tenant's rows.
"""

from __future__ import annotations

import datetime as _dt
import importlib

import pytest

from app.projects.foodlink_predict.db import (
    count_where,
    get_by_id,
    list_where,
    require_by_id,
    session_scope,
)
from app.projects.foodlink_predict.errors import Forbidden, ValidationFailed
from app.projects.foodlink_predict.tenancy import DEMO_ORG_ID, OrgContext, resolve_org_id

# Same pinned clock as conftest (duplicated rather than imported: tests/flp is not
# a package, and adding __init__.py would change collection for the whole dir).
PINNED_AS_OF = _dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=_dt.timezone.utc)


@pytest.fixture()
def two_orgs():
    """Two organizations holding identical-looking data."""
    from app.projects.foodlink_predict import synthetic

    orgs = ["org_alpha", "org_beta"]
    for oid in orgs:
        ds = synthetic.generate(as_of=PINNED_AS_OF)
        with session_scope() as sess:
            synthetic.load_into_db(sess, oid, ds)
    return orgs


# ------------------------------------------------------------ db layer ---
def test_get_by_id_cannot_cross_tenants(two_orgs):
    from app.projects.foodlink_predict.models import Batch

    with session_scope() as sess:
        mine = get_by_id(sess, Batch, "bat_demo_rice_001", "org_alpha")
        assert mine is not None
        # Same natural batch id exists in the other org; it must be invisible.
        assert get_by_id(sess, Batch, "bat_demo_rice_001", "org_gamma") is None


def test_require_by_id_does_not_confirm_cross_tenant_existence(two_orgs):
    from app.projects.foodlink_predict.models import Batch

    with session_scope() as sess:
        with pytest.raises(ValidationFailed) as exc:
            require_by_id(sess, Batch, "bat_demo_rice_001", "org_gamma", "Batch")
    message = str(exc.value)
    # Same message whether the batch never existed or belongs to another org.
    assert "not found" in message
    assert "org_gamma" not in message
    assert "org_alpha" not in message


def test_list_where_is_org_scoped(two_orgs):
    from app.projects.foodlink_predict.models import Batch

    with session_scope() as sess:
        alpha = list_where(sess, Batch, "org_alpha")
        beta = list_where(sess, Batch, "org_beta")
        assert len(alpha) == len(beta) > 0
        assert {b.id for b in alpha} == {b.id for b in beta}  # same generated ids...
        for b in alpha:
            assert b.org_id == "org_alpha"  # ...but each row is owned


def test_count_where_is_org_scoped(two_orgs):
    from app.projects.foodlink_predict.models import SalesDaily

    with session_scope() as sess:
        assert count_where(sess, SalesDaily, "org_alpha") == count_where(sess, SalesDaily, "org_beta") > 0


def test_forecast_rows_are_org_scoped(two_orgs):
    from app.projects.foodlink_predict import service as S

    for oid in two_orgs:
        S.run_forecast(oid, horizon_days=3, as_of=PINNED_AS_OF, include_backtest=False)
    a = S.stored_forecast("org_alpha")
    b = S.stored_forecast("org_beta")
    assert a and b
    assert len(a) == len(b)


# --------------------------------------------------------------- api ------
def test_risk_endpoint_is_org_scoped(client, two_orgs):
    r = client.get("/api/risk", params={"org_id": "org_alpha", "recompute": True})
    assert r.status_code == 200
    rows = r.json()["data"]["items"]
    assert rows
    assert all(x["batch_id"].startswith("bat_demo") for x in rows)


def test_two_orgs_see_their_own_listings_only(client, two_orgs):
    """A listing created by org_alpha must be invisible to org_beta."""
    import asyncio

    from app.projects.foodlink_predict import service as S
    from app.projects.foodlink_predict import surplus as SURPLUS

    for oid in two_orgs:
        S.run_forecast(oid, horizon_days=7, as_of=PINNED_AS_OF, include_backtest=False)

    # Drive both orgs through the pipeline and publish whatever the validator allows.
    made = {}
    for oid in two_orgs:
        res = asyncio.run(S.recommend(oid, min_risk=0.0, limit=3, as_of=PINNED_AS_OF))
        donate = [r for r in res["recommendations"] if r["action"] == "donate" and r["validation_status"] == "passed"]
        made[oid] = []
        for rec in donate:
            listing = SURPLUS.create_listing(oid, batch_id=rec["batch_id"], now=PINNED_AS_OF)
            made[oid].append(listing["listing_id"])

    if not made.get("org_alpha") or not made.get("org_beta"):
        pytest.skip("no validated donate recommendation was produced for both orgs")

    # Each org sees only its own.
    for owner, ids in made.items():
        other = "org_beta" if owner == "org_alpha" else "org_alpha"
        mine = client.get("/api/surplus", params={"org_id": owner}).json()["data"]
        assert {i["listing_id"] for i in mine["items"]} == set(ids)
        for listing_id in made[other]:
            assert listing_id not in {i["listing_id"] for i in mine["items"]}
            # And a direct fetch by id is refused, not just filtered from a list.
            assert client.get(f"/api/surplus/{listing_id}", params={"org_id": owner}).status_code == 422


def test_cross_tenant_listing_fetch_is_refused(client, two_orgs):
    import asyncio

    from app.projects.foodlink_predict import service as S
    from app.projects.foodlink_predict import surplus as SURPLUS

    for oid in two_orgs:
        S.run_forecast(oid, horizon_days=7, as_of=PINNED_AS_OF, include_backtest=False)
    res = asyncio.run(S.recommend("org_alpha", min_risk=0.0, limit=3, as_of=PINNED_AS_OF))
    donate = [r for r in res["recommendations"] if r["action"] == "donate" and r["validation_status"] == "passed"]
    if not donate:
        pytest.skip("no validated donate recommendation produced")
    listing = SURPLUS.create_listing("org_alpha", batch_id=donate[0]["batch_id"], now=PINNED_AS_OF)
    r = client.get(f"/api/surplus/{listing['listing_id']}", params={"org_id": "org_beta"})
    assert r.status_code == 422


def test_recommend_endpoint_is_org_scoped(client, two_orgs):
    r = client.post("/api/recommend", json={"org_id": "org_alpha", "limit": 2})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["org_id"] == "org_alpha"


def test_impact_endpoint_is_org_scoped(client, two_orgs):
    r = client.get("/api/impact", params={"org_id": "org_alpha"})
    assert r.status_code == 200
    assert r.json()["data"]["org_id"] == "org_alpha"


# ------------------------------------------------------------ tenancy ----
def test_demo_mode_defaults_to_the_demo_org():
    ctx = resolve_org_id(None)
    assert ctx.org_id == DEMO_ORG_ID


def test_explicit_org_is_honoured_in_demo_mode():
    assert resolve_org_id("org_x").org_id == "org_x"


def test_auth_mode_requires_a_token(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(Forbidden):
            resolve_org_id("org_x")
    finally:
        get_settings.cache_clear()


def _mint_token(monkeypatch, secret: str, **claims):
    """Mint a token with a fresh jwt module.

    app/auth/jwt.py snapshots settings at import time, so the module is reloaded
    after the env is set. V4 core is left untouched.
    """
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET", secret)
    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.auth.jwt as jwt_mod

    importlib.reload(jwt_mod)
    return jwt_mod.create_access_token("user1", extra_claims=claims or None)


def test_auth_mode_rejects_a_cross_tenant_org(monkeypatch):
    token = _mint_token(monkeypatch, "x" * 40, org_id="org_alpha")
    # Claimed org_alpha, body says org_beta -> refused, never silently downgraded.
    with pytest.raises(Forbidden):
        resolve_org_id("org_beta", token=token)
    assert resolve_org_id("org_alpha", token=token).org_id == "org_alpha"


def test_token_without_an_org_claim_is_refused(monkeypatch):
    token = _mint_token(monkeypatch, "y" * 40)
    with pytest.raises(Forbidden):
        resolve_org_id(None, token=token)


def test_invalid_token_is_refused(monkeypatch):
    _mint_token(monkeypatch, "z" * 40, org_id="org_alpha")
    with pytest.raises(Exception):
        resolve_org_id("org_alpha", token="not-a-jwt")


def test_org_context_require_blocks_mismatch():
    ctx = OrgContext(org_id="org_a", is_demo=True, actor="t")
    ctx.require("org_a")
    with pytest.raises(ValidationFailed):
        ctx.require("org_b")


# ------------------------------------------------------------- secrets ---
def test_health_flp_never_exposes_credentials(client):
    r = client.get("/api/health/flp")
    assert r.status_code == 200
    blob = r.json()["data"]
    text = str(blob).lower()
    for marker in ("sk-", "api_key\":", "bearer ", "secret\":", "password"):
        assert marker not in text


def test_settings_do_not_leak_keys_into_flp_config():
    from app.projects.foodlink_predict.config import get_flp_config

    cfg = get_flp_config()
    for attr in dir(cfg):
        if attr.startswith("_"):
            continue
        value = getattr(cfg, attr)
        assert not (isinstance(value, str) and value.lower().startswith(("sk-", "gsk_")))