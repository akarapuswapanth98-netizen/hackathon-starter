"""Adapter selection.

``FOODLINK_ADAPTER_MODE``:
  demo      (default) offline in-memory simulator. Every response is labelled.
  http      real HTTP call. Refuses to run until FOODLINK_API_URL and
            FOODLINK_LISTING_PATH are both set, because the listing contract is
            unverified and must be opted into deliberately.
  disabled  no adapter at all; surplus endpoints return a clear 503.
"""

from __future__ import annotations

import os
from typing import Any

from app.projects.foodlink_predict.adapters.base import (
    FoodLinkAdapter,
    FoodLinkError,
    FoodLinkUnavailable,
    canonical_listing,
)
from app.projects.foodlink_predict.adapters.demo import DemoFoodLinkAdapter
from app.projects.foodlink_predict.errors import CapabilityUnavailable

_INSTANCES: dict[str, Any] = {}


def get_adapter(mode: str | None = None) -> FoodLinkAdapter:
    from app.projects.foodlink_predict.config import get_flp_config

    cfg = get_flp_config()
    resolved = (mode or cfg.adapter_mode or "demo").strip().lower()

    if resolved == "demo":
        inst = _INSTANCES.get("demo")
        if inst is None:
            inst = DemoFoodLinkAdapter()
            _INSTANCES["demo"] = inst
        return inst

    if resolved == "http":
        inst = _INSTANCES.get("http")
        if inst is None:
            from app.projects.foodlink_predict.adapters.http import HttpFoodLinkAdapter

            inst = HttpFoodLinkAdapter(
                base_url=cfg.foodlink_api_url,
                listing_path=cfg.foodlink_listing_path,
                # Secret read here, passed in, never returned or logged in full.
                api_key=os.getenv("FOODLINK_API_KEY", ""),
            )
            _INSTANCES["http"] = inst
        return inst

    if resolved in ("disabled", "off", "none"):
        raise CapabilityUnavailable(
            "FoodLink integration is disabled (FOODLINK_ADAPTER_MODE=disabled)",
            detail="Set FOODLINK_ADAPTER_MODE=demo for the offline demo, or http once the real contract is configured",
        )

    raise CapabilityUnavailable(
        f"Unknown FOODLINK_ADAPTER_MODE '{resolved}'",
        detail="Supported: demo (default), http, disabled",
    )


def reset_adapters() -> None:
    """Test helper: drop cached adapter instances."""
    _INSTANCES.clear()


def describe() -> dict:
    """Adapter capability report for /health and the demo banner.

    Never returns credentials, only whether they exist.
    """
    from app.projects.foodlink_predict.config import get_flp_config

    cfg = get_flp_config()
    mode = cfg.adapter_mode
    info: dict[str, Any] = {
        "mode": mode,
        "configured": mode in ("demo", "http"),
        "demo": mode == "demo",
        "real_foodlink_executed": False,
        "contract_verified": False,
        "contract_status": "UNVERIFIED - the real FoodLink listing schema was never available to this module",
        "requires_credentials": mode == "http",
    }
    if mode == "http":
        info["ready"] = bool(cfg.foodlink_api_url and cfg.foodlink_listing_path)
        info["missing"] = [
            name
            for name, val in (("FOODLINK_API_URL", cfg.foodlink_api_url), ("FOODLINK_LISTING_PATH", cfg.foodlink_listing_path))
            if not val
        ]
        info["api_key_present"] = bool(os.getenv("FOODLINK_API_KEY", ""))
    else:
        info["ready"] = mode == "demo"
    return info


__all__ = [
    "FoodLinkAdapter",
    "FoodLinkError",
    "FoodLinkUnavailable",
    "canonical_listing",
    "describe",
    "get_adapter",
    "reset_adapters",
]