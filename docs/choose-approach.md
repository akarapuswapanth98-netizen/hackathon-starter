# Choosing an Approach - v2 Specification Guide

This document guides hackathon participants in selecting and enabling the right
modules for their problem, without rebuilding the entire application.

## Mode Selection (LIVE / DEMO / AUTO)

The application runs in one of three modes, configured via `APP_MODE` env var
or auto-detected:

| Mode | When Active | Characteristics |
|------|-------------|-----------------|
| **LIVE** | `APP_MODE=LIVE` and real LLM key + `DATABASE_URL` set | Real LLM calls, persistent storage, full features |
| **DEMO** | `APP_MODE=DEMO` or no real LLM key / no DB | Deterministic, in-memory, no tokens needed, demo reset available |
| **AUTO** (default) | `APP_MODE=AUTO` (env not set) | Auto-detects: LIVE if real key + DB, otherwise DEMO |

### Auto-detection logic

```
has_real_llm = LLM_PROVIDER != "mock" AND LLM_API_KEY is set
has_db      = DATABASE_URL is set

if has_real_llm and has_db:    mode = LIVE
else:                           mode = DEMO
```

## Storage Backend Selection

Three storage modes are available:

| Provider | When Active | Characteristics |
|----------|-------------|-----------------|
| **memory** | Default in DEMO mode | In-memory FoodBridge store, fast, non-persistent |
| **sqlalchemy** | Default in LIVE mode | SQLAlchemy + SQLite (default) or PostgreSQL |
| **custom** | `STORAGE_PROVIDER=sqlalchemy` explicitly | Configurable via `DATABASE_URL` env var |

### SQLite default

```
DATABASE_URL=sqlite:///./data/hackathon.db
```

### PostgreSQL

```
DATABASE_URL=postgresql://hackathon:hackathon@localhost:5432/hackathon
```

## ML/ML Template Selection

Four template families are available, installed optionally:

| Template Family | Dependencies | Use Case |
|----------------|-------------|----------|
| **Classification** | `scikit-learn`, `xgboost` (opt.), `shap` (opt.) | Binary/multiclass classification |
| **Regression** | `scikit-learn`, `xgboost` (opt.), `shap` (opt.) | Numeric prediction |
| **Computer Vision** | `ultralytics` (opt.), `opencv-python` (opt.) | Object detection, image analysis |
| **RAG** | `chromadb` (opt.), `sentence-transformers` (opt.) | Offline document retrieval |

### Enabling a template

```bash
# Example: Enable XGBoost + SHAP for classification
pip install scikit-learn xgboost shap

# Or via requirements extras (when supported)
pip install -r requirements.txt  # installs core only
# Then install optional deps as needed
```

## Maps Provider Selection

Three maps providers are available, from offline-first to external APIs:

| Provider | Dependency | Use Case |
|----------|------------|----------|
| **haversine** (default) | None | Great-circle distance, offline, always available |
| **osrm** | `urllib` | Routing via Open Source Routing Machine |
| **google** | Google Maps API key | Turn-by-turn routes, geocoding |
| **mapbox** | Mapbox access token | Custom maps, styles |

### Using haversine (default, no deps)

```python
from app.maps.provider import distance_km
d = distance_km(17.42, 78.48, 17.38, 78.50)  # ~2.1 km
```

### Switching provider

```bash
export MAPS_PROVIDER=osrm  # or google, mapbox
```

## Authentication Selection

JWT authentication is opt-in:

| Setting | Value | Effect |
|---------|-------|--------|
| `AUTH_ENABLED` | `true` | Enable auth routes + middleware |
| `AUTH_ENABLED` | `false` (default) | No auth routes, all endpoints public |

### When enabled

```bash
export AUTH_ENABLED=true
export JWT_SECRET=super-secret-key
# Login at POST /api/auth/login
# Protected routes require: Authorization: Bearer <token>
```

### When disabled (default)

All FoodBridge and API endpoints are available without tokens.

## Quick Start: Enable Only What You Need

```bash
# 1. Basic FoodBridge (demo mode, no auth, no DB persistence)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 2. With persistent SQLite storage
cd backend
pip install -r requirements.txt  # includes sqlalchemy, alembic
DATABASE_URL=sqlite:///./data/hackathon.db
uvicorn app.main:app --port 8000

# 3. With PostgreSQL
DATABASE_URL=postgresql://user:pw@host:5432/db
uvicorn app.main:app --port 8000

# 4. With ML classification template
pip install scikit-learn xgboost shap
# Import: from app.ml.templates import ClassificationTemplate

# 5. With CV / YOLO template
pip install ultralytics
# Import: from app.vision.templates import YOLODetectionTemplate

# 6. With RAG template
pip install chromadb
# Import: from app.rag.templates import ChromaDBStore

# 7. With maps provider (OSRM example)
export MAPS_PROVIDER=osrm

# 8. With authentication
export AUTH_ENABLED=true
export JWT_SECRET=my-key
uvicorn app.main:app --port 8000
```

## Decision Matrix

Choose the right combination for your hackathon problem:

```
                    ML?  CV?  RAG?  Auth?  DB?
-----------------------------------------------
FoodBridge only   --   --   --   --  mem
FoodBridge+ML     +    --   --   --  sql
FoodBridge+CV     --   +    --   --  sql
Full stack        +    +    +    +    sql
-----------------------------------------------
```

## Migration Path

1. **Start**: `APP_MODE=AUTO` (default) with in-memory FoodBridge
2. **Add storage**: Set `DATABASE_URL` → switches to `sqlalchemy` provider
3. **Add ML**: Install optional deps, import templates
4. **Add CV**: Install optional deps, import templates
5. **Add RAG**: Install optional deps, initialize pipeline
6. **Add maps**: Set `MAPS_PROVIDER` env var
7. **Add auth**: Set `AUTH_ENABLED=true`, configure JWT secrets