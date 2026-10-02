"""SQLAlchemy models for persistent FoodBridge storage."""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RestaurantModel(Base):
    __tablename__ = "restaurants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str] = mapped_column(String(512), default="")
    cuisine_types: Mapped[list] = mapped_column(JSON, default=list)
    contact: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    surpluses: Mapped[list["SurplusModel"]] = relationship(
        back_populates="restaurant", cascade="all, delete-orphan"
    )

    def to_pydantic(self) -> "Restaurant":
        from app.foodbridge.models import Restaurant
        return Restaurant(
            id=self.id,
            name=self.name,
            lat=self.lat,
            lon=self.lon,
            address=self.address,
            cuisine_types=self.cuisine_types,
            contact=self.contact,
        )


class SurplusModel(Base):
    __tablename__ = "surpluses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    restaurant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("restaurants.id"), nullable=False
    )
    meal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    food_type: Mapped[str] = mapped_column(String(64), default="cooked_meals")
    dietary_tags: Mapped[list] = mapped_column(JSON, default=list)
    prepared_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, default=5.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="available")
    reserved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    restaurant: Mapped["RestaurantModel"] = relationship(back_populates="surpluses")
    match_results: Mapped[list["MatchResultModel"]] = relationship(
        back_populates="surplus", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_surpluses_restaurant_id", "restaurant_id"),
        Index("ix_surpluses_status", "status"),
    )

    def to_pydantic(self) -> "FoodSurplus":
        from app.foodbridge.models import FoodSurplus
        return FoodSurplus(
            id=self.id,
            restaurant_id=self.restaurant_id,
            meal_count=self.meal_count,
            food_type=self.food_type,
            dietary_tags=self.dietary_tags,
            prepared_at=self.prepared_at,
            expires_at=self.expires_at,
            temperature_c=self.temperature_c,
            notes=self.notes,
            status=self.status,
        )


class ShelterModel(Base):
    __tablename__ = "shelters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    current_occupancy: Mapped[int] = mapped_column(Integer, default=0)
    urgency: Mapped[str] = mapped_column(String(16), default="medium")
    food_requirements: Mapped[list] = mapped_column(JSON, default=list)
    address: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    match_results: Mapped[list["MatchResultModel"]] = relationship(
        back_populates="shelter", cascade="all, delete-orphan"
    )

    def to_pydantic(self) -> "Shelter":
        from app.foodbridge.models import Shelter
        return Shelter(
            id=self.id,
            name=self.name,
            lat=self.lat,
            lon=self.lon,
            capacity=self.capacity,
            current_occupancy=self.current_occupancy,
            urgency=self.urgency,
            food_requirements=self.food_requirements,
            address=self.address,
        )


class MatchResultModel(Base):
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    surplus_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("surpluses.id"), nullable=False, index=True
    )
    shelter_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("shelters.id"), nullable=False, index=True
    )
    meals: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    total_allocated: Mapped[int] = mapped_column(Integer, nullable=False)
    unallocated: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    surplus: Mapped["SurplusModel"] = relationship(back_populates="match_results")
    shelter: Mapped["ShelterModel"] = relationship(back_populates="match_results")

    __table_args__ = (
        Index("ix_match_results_workflow_surplus", "workflow_id", "surplus_id"),
    )


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    integrity_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_correlation", "correlation_id"),
    )