"""SQLAlchemy storage provider - SQLite default, PostgreSQL-ready."""
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.foodbridge.models import FoodSurplus, Restaurant, Shelter
from app.storage.base import StorageProvider
from app.storage.models import (
    AuditLogModel,
    Base,
    MatchResultModel,
    RestaurantModel,
    ShelterModel,
    SurplusModel,
)


class SQLAlchemyProvider(StorageProvider):
    """SQLAlchemy-backed storage - works with SQLite (default) or PostgreSQL."""

    _instance: Optional["SQLAlchemyProvider"] = None
    _lock = threading.Lock()

    def __new__(cls, database_url: Optional[str] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, database_url: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return

        # Default to SQLite in ./data/hackathon.db
        if database_url is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
            os.makedirs(data_dir, exist_ok=True)
            database_url = f"sqlite:///{os.path.join(data_dir, 'hackathon.db')}"

        self.database_url = database_url
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._init_engine()
        self._init_db()
        self._seed_demo()
        self._initialized = True

    def _init_engine(self):
        connect_args = {}
        if self.database_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            # Enable WAL mode for better concurrency
            def _set_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()

            event.listen(Engine, "connect", _set_pragma)

        self._engine = create_engine(
            self.database_url,
            connect_args=connect_args,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False, autoflush=False
        )

    @contextmanager
    def _session(self) -> Session:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _init_db(self):
        Base.metadata.create_all(self._engine)

    def _seed_demo(self):
        """Seed demo data if empty."""
        with self._session() as session:
            if session.query(RestaurantModel).count() == 0:
                self._seed_demo_data(session)

    def _seed_demo_data(self, session: Session):
        """Seed demo data matching the in-memory store."""
        from datetime import datetime, timedelta, timezone

        utcnow = datetime.now(timezone.utc)

        restaurant = RestaurantModel(
            id="rest-001",
            name="Green Leaf Restaurant",
            lat=17.4200,
            lon=78.4800,
            address="12 Banjara Lane, Hyderabad",
            cuisine_types=["north-indian", "veg"],
            contact="+91-90000-11111",
        )
        session.add(restaurant)

        lot = SurplusModel(
            id="food-001",
            restaurant_id=restaurant.id,
            meal_count=80,
            food_type="cooked_meals",
            dietary_tags=["vegetarian"],
            prepared_at=utcnow - timedelta(hours=1),
            expires_at=utcnow + timedelta(hours=5),
            temperature_c=5.0,
            notes="Fresh vegetarian lunch service surplus",
        )
        session.add(lot)

        shelters = [
            ShelterModel(
                id="shelter-a",
                name="Shelter A - Govt. Higher Secondary School",
                lat=17.4390,
                lon=78.4800,
                capacity=60,
                current_occupancy=10,
                urgency="high",
                food_requirements=["vegetarian"],
                address="School Compound, North Colony",
            ),
            ShelterModel(
                id="shelter-b",
                name="Shelter B - Community Hall",
                lat=17.3775,
                lon=78.4800,
                capacity=40,
                current_occupancy=10,
                urgency="medium",
                food_requirements=["vegetarian"],
                address="Old Market Road",
            ),
            ShelterModel(
                id="shelter-c",
                name="Shelter C - Night Shelter Trust",
                lat=17.4200,
                lon=78.5101,
                capacity=80,
                current_occupancy=10,
                urgency="high",
                food_requirements=["vegetarian"],
                address="Trust Building, East Side",
            ),
        ]
        for s in shelters:
            session.add(s)

        session.flush()

    # --- Restaurants ---
    def get_restaurant(self, restaurant_id: str) -> Optional[Restaurant]:
        with self._session() as session:
            model = session.get(RestaurantModel, restaurant_id)
            return model.to_pydantic() if model else None

    def list_restaurants(self) -> List[Restaurant]:
        with self._session() as session:
            return [m.to_pydantic() for m in session.query(RestaurantModel).all()]

    def add_restaurant(self, restaurant: Restaurant) -> Restaurant:
        with self._session() as session:
            model = RestaurantModel(
                id=restaurant.id,
                name=restaurant.name,
                lat=restaurant.lat,
                lon=restaurant.lon,
                address=restaurant.address,
                cuisine_types=restaurant.cuisine_types,
                contact=restaurant.contact,
            )
            session.add(model)
            session.flush()
            return model.to_pydantic()

    # --- Surplus ---
    def get_surplus(self, surplus_id: str) -> Optional[FoodSurplus]:
        with self._session() as session:
            model = session.get(SurplusModel, surplus_id)
            return model.to_pydantic() if model else None

    def list_surpluses(self, restaurant_id: Optional[str] = None) -> List[FoodSurplus]:
        with self._session() as session:
            q = session.query(SurplusModel)
            if restaurant_id:
                q = q.filter(SurplusModel.restaurant_id == restaurant_id)
            return [m.to_pydantic() for m in q.order_by(SurplusModel.prepared_at.desc()).all()]

    def list_available_surpluses(self, restaurant_id: Optional[str] = None) -> List[FoodSurplus]:
        with self._session() as session:
            q = session.query(SurplusModel).filter(SurplusModel.status == "available")
            if restaurant_id:
                q = q.filter(SurplusModel.restaurant_id == restaurant_id)
            return [m.to_pydantic() for m in q.order_by(SurplusModel.prepared_at.desc()).all()]

    def latest_surplus(self, restaurant_id: Optional[str] = None) -> Optional[FoodSurplus]:
        lots = self.list_available_surpluses(restaurant_id)
        return lots[0] if lots else None

    def add_surplus(self, lot: FoodSurplus) -> FoodSurplus:
        with self._session() as session:
            model = SurplusModel(
                id=lot.id,
                restaurant_id=lot.restaurant_id,
                meal_count=lot.meal_count,
                food_type=lot.food_type,
                dietary_tags=lot.dietary_tags,
                prepared_at=lot.prepared_at,
                expires_at=lot.expires_at,
                temperature_c=lot.temperature_c,
                notes=lot.notes,
                status=lot.status,
            )
            session.add(model)
            session.flush()
            return model.to_pydantic()

    def commit_allocation(self, surplus_id: str, total_allocated: int) -> Optional[FoodSurplus]:
        with self._session() as session:
            model = session.get(SurplusModel, surplus_id)
            if model is None or model.status != "available":
                return model.to_pydantic() if model else None
            total = int(total_allocated or 0)
            if total <= 0:
                return model.to_pydantic()
            if total >= model.meal_count:
                model.status = "allocated"
            else:
                model.meal_count -= total
            model.updated_at = datetime.now(timezone.utc)
            session.flush()
            return model.to_pydantic()

    def reserve_surplus(self, surplus_id: str) -> bool:
        with self._session() as session:
            model = session.get(SurplusModel, surplus_id)
            if model is None or model.status != "available" or model.reserved:
                return False
            model.reserved = True
            model.updated_at = datetime.now(timezone.utc)
            session.flush()
            return True

    def release_surplus(self, surplus_id: str) -> None:
        with self._session() as session:
            model = session.get(SurplusModel, surplus_id)
            if model:
                model.reserved = False
                model.updated_at = datetime.now(timezone.utc)
                session.flush()

    # --- Shelters ---
    def get_shelter(self, shelter_id: str) -> Optional[Shelter]:
        with self._session() as session:
            model = session.get(ShelterModel, shelter_id)
            return model.to_pydantic() if model else None

    def list_shelters(self) -> List[Shelter]:
        with self._session() as session:
            return [m.to_pydantic() for m in session.query(ShelterModel).all()]

    def add_shelter(self, shelter: Shelter) -> Shelter:
        with self._session() as session:
            model = ShelterModel(
                id=shelter.id,
                name=shelter.name,
                lat=shelter.lat,
                lon=shelter.lon,
                capacity=shelter.capacity,
                current_occupancy=shelter.current_occupancy,
                urgency=shelter.urgency,
                food_requirements=shelter.food_requirements,
                address=shelter.address,
            )
            session.add(model)
            session.flush()
            return model.to_pydantic()

    # --- Lifecycle ---
    def reset(self) -> None:
        with self._session() as session:
            session.query(MatchResultModel).delete()
            session.query(AuditLogModel).delete()
            session.query(SurplusModel).delete()
            session.query(ShelterModel).delete()
            session.query(RestaurantModel).delete()
            session.flush()
            self._seed_demo_data(session)

    def close(self) -> None:
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

    # --- Match History / Audit ---
    def record_match_result(
        self,
        workflow_id: str,
        surplus_id: str,
        allocations: List[Dict[str, Any]],
        total_allocated: int,
        unallocated: int,
        status: str,
        metadata: Dict[str, Any],
    ) -> None:
        with self._session() as session:
            for alloc in allocations:
                result = MatchResultModel(
                    workflow_id=workflow_id,
                    surplus_id=surplus_id,
                    shelter_id=alloc["shelter_id"],
                    meals=alloc["meals"],
                    distance_km=alloc["distance_km"],
                    score=alloc["score"],
                    breakdown=alloc.get("breakdown", {}),
                    total_allocated=total_allocated,
                    unallocated=unallocated,
                    workflow_status=status,
                    metadata=metadata,
                )
                session.add(result)

            # Audit log
            self._write_audit_log(
                session,
                entity_type="match",
                entity_id=workflow_id,
                action="create",
                after={
                    "workflow_id": workflow_id,
                    "surplus_id": surplus_id,
                    "total_allocated": total_allocated,
                    "unallocated": unallocated,
                    "status": status,
                },
                correlation_id=workflow_id,
            )
            session.flush()

    def get_match_history(
        self,
        surplus_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._session() as session:
            q = session.query(MatchResultModel)
            if surplus_id:
                q = q.filter(MatchResultModel.surplus_id == surplus_id)
            results = q.order_by(MatchResultModel.created_at.desc()).limit(limit).all()
            return [
                {
                    "workflow_id": r.workflow_id,
                    "surplus_id": r.surplus_id,
                    "shelter_id": r.shelter_id,
                    "meals": r.meals,
                    "distance_km": r.distance_km,
                    "score": r.score,
                    "breakdown": r.breakdown,
                    "total_allocated": r.total_allocated,
                    "unallocated": r.unallocated,
                    "workflow_status": r.workflow_status,
                    "metadata": r.result_metadata,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in results
            ]

    def _write_audit_log(
        self,
        session: Session,
        entity_type: str,
        entity_id: str,
        action: str,
        before: Optional[dict] = None,
        after: Optional[dict] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Write audit log with SHA-256 integrity hash."""
        before_json = json.dumps(before, sort_keys=True) if before else ""
        after_json = json.dumps(after, sort_keys=True) if after else ""
        integrity_input = f"{entity_type}:{entity_id}:{action}:{before_json}:{after_json}:{datetime.now(timezone.utc).isoformat()}"
        integrity_hash = hashlib.sha256(integrity_input.encode()).hexdigest()

        log = AuditLogModel(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
            user_id=user_id,
            correlation_id=correlation_id,
            integrity_hash=integrity_hash,
        )
        session.add(log)