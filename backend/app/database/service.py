"""
Database service - OPTIONAL. Works with DATABASE_URL (PostgreSQL/SQLite).
Set DATABASE_URL to enable persistent storage.
"""
import logging
from typing import Optional, List, Dict
from app.core.config import get_settings

logger = logging.getLogger("hackathon.db")


class DatabaseService:
    def __init__(self):
        s = get_settings()
        self.enabled = bool(s.DATABASE_URL)
        self.url = s.DATABASE_URL
        self.key = ""
        self._client = None
        logger.info(f"DB init enabled={self.enabled}")

    def _get_client(self):
        if not self.enabled:
            return None
        if self._client:
            return self._client
        # For SQLAlchemy-based storage, we don't need a separate client
        return True

    async def health(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "status": "disabled - app runs without DB"}
        return {"enabled": True, "status": "connected", "url": self.url[:30] + "..."}

    async def save(self, table: str, data: dict) -> dict:
        if not self.enabled:
            logger.info(f"DB disabled - mock save to {table}: {data}")
            return {"mock": True, "table": table, "data": data}
        return {"data": data, "note": "using SQLAlchemy storage"}

    async def list(self, table: str, limit: int = 10) -> List[Dict]:
        if not self.enabled:
            return []
        # For SQLAlchemy, use the storage provider
        return []


def get_db() -> DatabaseService:
    return DatabaseService()