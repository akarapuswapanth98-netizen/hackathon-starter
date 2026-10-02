"""Storage provider factory - returns appropriate provider based on config.

Note: Imports from app.foodbridge.* are done lazily inside functions to avoid
circular imports (foodbridge.agents -> storage.factory -> storage.base -> foodbridge.models).
"""

from functools import lru_cache
from typing import Optional

from app.core.config import get_settings


@lru_cache
def get_storage_provider(database_url: Optional[str] = None) -> "StorageProvider":
    """Get the appropriate storage provider based on settings.

    Returns:
        StorageProvider instance (SQLAlchemyProvider or MemoryProvider)
    """
    from app.storage.sqlalchemy_provider import SQLAlchemyProvider
    from app.storage.memory_provider import MemoryProvider
    from app.storage.base import StorageProvider

    settings = get_settings()
    provider_type = settings.get_storage_provider()

    if provider_type == "sqlalchemy":
        url = database_url or settings.get_database_url()
        return SQLAlchemyProvider(database_url=url)
    else:
        return MemoryProvider()


def reset_storage_provider() -> None:
    """Reset the cached storage provider (for tests)."""
    get_storage_provider.cache_clear()