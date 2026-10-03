"""Database access for FoodLink Predict.

Owns its own engine (SQLite by default) and its own Base metadata, so enabling
this project can never migrate, drop or shadow a starter table.

Tenant isolation is enforced here, not in the routes: every helper takes
``org_id`` and puts it in the WHERE clause. A caller that forgets the filter
gets an empty result instead of another tenant's rows.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.projects.foodlink_predict.config import default_db_url
from app.projects.foodlink_predict.errors import PersistenceError, ValidationFailed
from app.projects.foodlink_predict.models import ALL_TABLES, FLPBase

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_engine_url: str | None = None
_lock = threading.RLock()


def _ensure_parent_dir(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    path = url.split("sqlite:///")[-1].split("?")[0]
    if not path or path == ":memory:":
        return
    from pathlib import Path

    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def get_engine(url: str | None = None) -> Engine:
    """Process-wide engine for FLP. Safe for SQLite + Postgres URLs."""
    global _engine, _session_factory, _engine_url
    resolved = url or default_db_url()
    with _lock:
        if _engine is None or _engine_url != resolved:
            _ensure_parent_dir(resolved)
            kwargs: dict[str, Any] = {"future": True}
            if resolved.startswith("sqlite"):
                # check_same_thread=False: FastAPI serves sync deps on a threadpool.
                kwargs["connect_args"] = {"check_same_thread": False}
            try:
                new_engine = create_engine(resolved, **kwargs)
                FLPBase.metadata.create_all(new_engine)
            except SQLAlchemyError as exc:
                raise PersistenceError(
                    "Cannot initialise the FoodLink Predict database",
                    detail=str(exc)[:300],
                ) from exc
            if _engine is not None:
                try:
                    _engine.dispose()
                except Exception:
                    pass
            _engine = new_engine
            _session_factory = sessionmaker(bind=new_engine, expire_on_commit=False, future=True)
            _engine_url = resolved
        return _engine


def reset_engine() -> None:
    """Drop the cached engine. Tests use this to swap to a temp DB."""
    global _engine, _session_factory, _engine_url
    with _lock:
        if _engine is not None:
            try:
                _engine.dispose()
            except Exception:
                pass
        _engine = None
        _session_factory = None
        _engine_url = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    factory = _session_factory
    if factory is None:
        get_engine()
        factory = _session_factory
    assert factory is not None
    sess = factory()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


# --------------------------------------------------------------------------
# Tenant-scoped helpers
# --------------------------------------------------------------------------
def insert(sess: Session, obj: Any) -> Any:
    sess.add(obj)
    sess.flush()
    return obj


def get_by_id(sess: Session, model: type, entity_id: str, org_id: str) -> Any | None:
    """Fetch one row *within a tenant*. org_id is part of the filter, always."""
    if not entity_id or org_id is None:
        return None
    stmt = select(model).where(model.id == entity_id)
    if hasattr(model, "org_id"):
        stmt = stmt.where(model.org_id == org_id)
    return sess.execute(stmt).scalars().first()


def require_by_id(sess: Session, model: type, entity_id: str, org_id: str, label: str) -> Any:
    row = get_by_id(sess, model, entity_id, org_id)
    if row is None:
        # Same message whether it never existed or belongs to another org:
        # leaking that distinction would let a caller probe other tenants.
        raise ValidationFailed(f"{label} '{entity_id}' not found for this organization")
    return row


def list_where(
    sess: Session,
    model: type,
    org_id: str,
    *,
    order_by: Any = None,
    limit: int | None = None,
    **filters: Any,
) -> list[Any]:
    stmt = select(model)
    if hasattr(model, "org_id"):
        stmt = stmt.where(model.org_id == org_id)
    for k, v in filters.items():
        if v is None:
            continue
        stmt = stmt.where(getattr(model, k) == v)
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(sess.execute(stmt).scalars().all())


def count_where(sess: Session, model: type, org_id: str, **filters: Any) -> int:
    from sqlalchemy import func

    stmt = select(func.count()).select_from(model)
    if hasattr(model, "org_id"):
        stmt = stmt.where(model.org_id == org_id)
    for k, v in filters.items():
        if v is None:
            continue
        stmt = stmt.where(getattr(model, k) == v)
    return int(sess.execute(stmt).scalar_one())


def delete_where(sess: Session, model: type, org_id: str, **filters: Any) -> int:
    stmt = delete(model)
    if hasattr(model, "org_id"):
        stmt = stmt.where(model.org_id == org_id)
    for k, v in filters.items():
        if v is None:
            continue
        stmt = stmt.where(getattr(model, k) == v)
    res = sess.execute(stmt)
    return int(res.rowcount or 0)


def table_names() -> Sequence[str]:
    return tuple(t.__tablename__ for t in ALL_TABLES)


def ping() -> bool:
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False