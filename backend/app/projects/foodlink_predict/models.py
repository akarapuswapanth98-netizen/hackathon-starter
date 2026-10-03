"""SQLAlchemy ORM models for FoodLink Predict.

Mirrors the PDF's section 6 data model. Two deliberate decisions:

* Every tenant-scoped table carries ``org_id`` so a single WHERE clause can
  enforce isolation (rule 19/20). Even child tables that can be reached via a
  parent carry it, so a query never has to join across a boundary to be safe.
* ``surplus_listings`` is the single FoodLink-facing seam. Its columns are the
  proposed contract from PDF section 5 and are mapped 1:1 by
  ``adapters/base.py`` - nothing else in this module knows FoodLink exists.

``utcnow()`` is used instead of the deprecated ``datetime.utcnow``.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class FLPBase(DeclarativeBase):
    """Own metadata so ``create_all`` touches only these tables."""

    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


# --------------------------------------------------------------------------
# Tenancy
# --------------------------------------------------------------------------
class Organization(FLPBase):
    __tablename__ = "flp_organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # restaurant | supermarket | cafeteria | hotel
    type: Mapped[str] = mapped_column(String(32), default="cafeteria")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)


class Location(FLPBase):
    __tablename__ = "flp_locations"
    __table_args__ = (Index("ix_flp_locations_org", "org_id"),)

    # Composite key: the same location id may exist independently in two orgs.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("flp_organizations.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lng: Mapped[float] = mapped_column(Float, default=0.0)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------
# Catalogue + inventory
# --------------------------------------------------------------------------
class Item(FLPBase):
    __tablename__ = "flp_items"
    __table_args__ = (Index("ix_flp_items_org", "org_id"),)

    # Composite key: item ids come from the customer's own catalogue, so they are
    # only unique within an organization.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("flp_organizations.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="other")
    unit: Mapped[str] = mapped_column(String(32), default="portion")
    shelf_life_hours: Mapped[float] = mapped_column(Float, default=24.0)
    # cooked | chilled | packaged | produce
    food_class: Mapped[str] = mapped_column(String(32), default="cooked")
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    # grams of food in one `unit`; needed to convert qty -> kg for the impact ledger.
    unit_weight_kg: Mapped[float] = mapped_column(Float, default=0.35)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)


class Batch(FLPBase):
    __tablename__ = "flp_batches"
    __table_args__ = (
        Index("ix_flp_batches_org", "org_id"),
        Index("ix_flp_batches_item", "org_id", "item_id"),
        Index("ix_flp_batches_location", "org_id", "location_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("flp_organizations.id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    location_id: Mapped[str] = mapped_column(String(64), nullable=False)
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    received_or_prepared_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)
    storage: Mapped[str] = mapped_column(String(32), default="ambient")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)


# NOTE: no ORM relationships between tenant-scoped tables. Their parent keys are
# composite, so a single-column ForeignKey would be wrong; every read goes
# through an explicit org-scoped query in db.py instead. That is also what makes
# tenant filtering impossible to forget.


# --------------------------------------------------------------------------
# Observed data
# --------------------------------------------------------------------------
class SalesDaily(FLPBase):
    __tablename__ = "flp_sales_daily"
    __table_args__ = (
        # Duplicate-day protection: the natural key of the source data.
        UniqueConstraint("org_id", "date", "item_id", "location_id", name="uq_flp_sales_natural"),
        Index("ix_flp_sales_org_date", "org_id", "date"),
        Index("ix_flp_sales_series", "org_id", "item_id", "location_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    location_id: Mapped[str] = mapped_column(String(64), nullable=False)
    qty_sold: Mapped[float] = mapped_column(Float, default=0.0)
    promo_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    # 'uploaded' | 'synthetic' - synthetic rows are labelled, never disguised.
    source: Mapped[str] = mapped_column(String(16), default="uploaded")


class CalendarDay(FLPBase):
    __tablename__ = "flp_calendar_days"
    __table_args__ = (
        UniqueConstraint("org_id", "date", name="uq_flp_calendar_natural"),
        Index("ix_flp_calendar_org_date", "org_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    region: Mapped[str] = mapped_column(String(64), default="default")
    is_holiday: Mapped[bool] = mapped_column(Boolean, default=False)
    holiday_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    day_of_week: Mapped[int] = mapped_column(Integer, default=0)
    weather: Mapped[str | None] = mapped_column(String(128), nullable=True)


# --------------------------------------------------------------------------
# Model output
# --------------------------------------------------------------------------
class Forecast(FLPBase):
    __tablename__ = "flp_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "item_id", "location_id", "target_date", "model_version", name="uq_flp_forecast_natural"
        ),
        Index("ix_flp_forecast_lookup", "org_id", "item_id", "location_id", "target_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    location_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    p10: Mapped[float] = mapped_column(Float, default=0.0)
    p50: Mapped[float] = mapped_column(Float, default=0.0)
    p90: Mapped[float] = mapped_column(Float, default=0.0)
    model_version: Mapped[str] = mapped_column(String(64), default="unknown")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)
    # 'model' | 'cold_start' - how the numbers were produced.
    method: Mapped[str] = mapped_column(String(16), default="model")


class WasteRisk(FLPBase):
    __tablename__ = "flp_waste_risk"
    __table_args__ = (
        Index("ix_flp_risk_org_computed", "org_id", "computed_at"),
        Index("ix_flp_risk_batch", "org_id", "batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)
    expected_unsold: Mapped[float] = mapped_column(Float, default=0.0)
    risk: Mapped[float] = mapped_column(Float, default=0.0)
    urgency_hours: Mapped[float] = mapped_column(Float, default=0.0)
    donate_by: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    priority: Mapped[float] = mapped_column(Float, default=0.0)
    # Full deterministic breakdown (p10/p50/p90 demand, value at risk, window).
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Recommendation(FLPBase):
    __tablename__ = "flp_recommendations"
    __table_args__ = (
        Index("ix_flp_rec_org_status", "org_id", "status"),
        Index("ix_flp_rec_batch", "org_id", "batch_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="")
    tool_trace: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    # Deterministic outputs the validator checked.
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    deadline: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_status: Mapped[str] = mapped_column(String(16), default="unknown")
    validation_errors: Mapped[list[Any]] = mapped_column(JSON, default=list)
    model_version: Mapped[str] = mapped_column(String(64), default="unknown")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)


class SurplusListing(FLPBase):
    """The ONE FoodLink-facing table.

    Field names follow the PDF's proposed contract (section 5). They are mapped
    here and translated by ``adapters/base.py``; if the real FoodLink schema
    differs, only that adapter file changes.
    """

    __tablename__ = "flp_surplus_listings"
    __table_args__ = (Index("ix_flp_listing_org_status", "org_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lng: Mapped[float] = mapped_column(Float, default=0.0)
    items: Mapped[list[Any]] = mapped_column(JSON, default=list)
    ready_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    donate_by: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    storage: Mapped[str] = mapped_column(String(32), default="ambient")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # forecast | confirmed | withdrawn
    status: Mapped[str] = mapped_column(String(16), default="forecast")
    source: Mapped[str] = mapped_column(String(32), default="waste-predictor")
    qty_kg: Mapped[float] = mapped_column(Float, default=0.0)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    withdrawn_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ImpactEvent(FLPBase):
    __tablename__ = "flp_impact_events"
    __table_args__ = (
        Index("ix_flp_impact_org_recorded", "org_id", "recorded_at"),
        Index("ix_flp_impact_rec", "org_id", "recommendation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kg_saved: Mapped[float] = mapped_column(Float, default=0.0)
    meals: Mapped[float] = mapped_column(Float, default=0.0)
    money_saved: Mapped[float] = mapped_column(Float, default=0.0)
    co2e_kg: Mapped[float] = mapped_column(Float, default=0.0)
    action_type: Mapped[str] = mapped_column(String(32), default="donate")
    recorded_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RunRecord(FLPBase):
    """Every FLP run (request_id, model version, outcome) for observability.

    Stores metadata only - never prompts containing secrets, never tokens.
    """

    __tablename__ = "flp_runs"
    __table_args__ = (Index("ix_flp_runs_org", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="")
    stage: Mapped[str] = mapped_column(String(32), default="")
    model_version: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="ok")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tool_calls: Mapped[list[Any]] = mapped_column(JSON, default=list)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=utcnow)


ALL_TABLES = (
    Organization,
    Location,
    Item,
    Batch,
    SalesDaily,
    CalendarDay,
    Forecast,
    WasteRisk,
    Recommendation,
    SurplusListing,
    ImpactEvent,
    RunRecord,
)