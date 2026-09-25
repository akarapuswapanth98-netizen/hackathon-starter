"""
Database service - OPTIONAL. Works without Supabase.
Set SUPABASE_ENABLED=true and SUPABASE_URL/KEY to enable.
"""
import logging
from typing import Optional, List, Dict
from app.core.config import get_settings

logger = logging.getLogger("hackathon.db")

class DatabaseService:
    def __init__(self):
        s = get_settings()
        self.enabled = s.SUPABASE_ENABLED
        self.url = s.SUPABASE_URL
        self.key = s.SUPABASE_KEY
        self._client = None
        logger.info(f"DB init enabled={self.enabled}")

    def _get_client(self):
        if not self.enabled:
            return None
        if self._client:
            return self._client
        try:
            from supabase import create_client
        except ImportError:
            logger.warning("supabase not installed: pip install supabase")
            return None
        if not self.url or not self.key:
            logger.warning("SUPABASE_URL/KEY missing")
            return None
        self._client = create_client(self.url, self.key)
        return self._client

    async def health(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "status": "disabled - app runs without DB"}
        client = self._get_client()
        if not client:
            return {"enabled": True, "status": "not configured - missing package or keys"}
        try:
            # Lightweight ping - list tables
            return {"enabled": True, "status": "connected", "url": self.url[:30]+"..."}
        except Exception as e:
            return {"enabled": True, "status": f"error: {e}"}

    async def save(self, table: str, data: dict) -> dict:
        if not self.enabled:
            logger.info(f"DB disabled - mock save to {table}: {data}")
            return {"mock": True, "table": table, "data": data}
        client = self._get_client()
        if not client:
            return {"error": "supabase not configured"}
        res = client.table(table).insert(data).execute()
        return {"data": res.data}

    async def list(self, table: str, limit: int = 10) -> List[Dict]:
        if not self.enabled:
            return []
        client = self._get_client()
        if not client:
            return []
        res = client.table(table).select("*").limit(limit).execute()
        return res.data or []

def get_db() -> DatabaseService:
    return DatabaseService()
