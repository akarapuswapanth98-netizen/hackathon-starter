"""HTTP FoodLink adapter - DISABLED by default, on purpose.

The architecture PDF is explicit that the real FoodLink listing schema could not
be inspected and that the proposed contract "should be checked against your
actual FoodLink schema". This module therefore does **not** guess:

* With no ``FOODLINK_LISTING_PATH`` configured, every method raises
  ``FoodLinkUnavailable`` explaining exactly which setting is missing. Nothing
  is sent anywhere.
* With a path configured, it POSTs Predict's canonical listing document
  verbatim and records that the wire format is UNVERIFIED in both the request
  log line and the response envelope.

To go live against the real FoodLink, edit ``map_to_foodlink_payload`` below to
translate canonical -> their schema, and ``parse_response`` to read theirs back.
That is the entire integration. No route, model, agent or test elsewhere in this
codebase needs to change.
"""

from __future__ import annotations

import logging
from typing import Any

from app.projects.foodlink_predict.adapters.base import (
    FoodLinkError,
    FoodLinkUnavailable,
    ListingRejected,
)
from app.projects.foodlink_predict.util import redact

logger = logging.getLogger("flp.foodlink.http")


class HttpFoodLinkAdapter:
    mode = "http"

    def __init__(
        self,
        *,
        base_url: str = "",
        listing_path: str = "",
        timeout_s: float = 8.0,
        api_key: str = "",
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.listing_path = listing_path or ""
        self.timeout_s = float(timeout_s)
        # Read from the environment only; never logged in full.
        self._api_key = api_key or ""

    # -- contract plumbing ------------------------------------------------
    def _require_config(self) -> None:
        missing = []
        if not self.base_url:
            missing.append("FOODLINK_API_URL")
        if not self.listing_path:
            missing.append("FOODLINK_LISTING_PATH")
        if missing:
            raise FoodLinkUnavailable(
                "FoodLink HTTP contract is not configured; set " + ", ".join(missing) + " before using FOODLINK_ADAPTER_MODE=http",
                reason="contract_not_configured",
            )

    def map_to_foodlink_payload(self, listing: dict) -> dict:
        """Translate canonical -> FoodLink wire format.

        DEFAULT: pass-through, flagged as unverified. Override this method (or
        subclass) once the real schema is known.
        """
        return dict(listing)

    def parse_response(self, payload: Any) -> dict:
        """Translate a FoodLink response -> Predict's status shape."""
        if not isinstance(payload, dict):
            raise ListingRejected("FoodLink returned a non-object response", reason="malformed_response")
        return {
            "external_status": payload.get("status") or payload.get("state") or "unknown",
            "external_ref": payload.get("id") or payload.get("listing_id") or payload.get("reference"),
            "raw_keys": sorted(payload.keys())[:20],
        }

    # -- interface --------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        self._require_config()
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx is a core dep
            raise FoodLinkUnavailable("httpx is required for the HTTP FoodLink adapter", reason="missing_dependency") from exc

        headers = {"Content-Type": "application/json", "X-FLP-Contract": "flp-listing/1"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        url = f"{self.base_url}{path}"
        # Log the destination and the key's tail only - never the key itself.
        logger.info(
            "foodlink %s %s api_key=%s contract=UNVERIFIED",
            method,
            url,
            redact(self._api_key) if self._api_key else "none",
        )
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.request(method, url, json=body, headers=headers)
        except Exception as exc:  # network error / timeout
            raise FoodLinkUnavailable(f"FoodLink request failed: {type(exc).__name__}", reason="network_error") from exc

        if resp.status_code >= 500:
            raise FoodLinkUnavailable(f"FoodLink returned {resp.status_code}", reason="upstream_error")
        if resp.status_code >= 400:
            raise ListingRejected(
                f"FoodLink rejected the listing with {resp.status_code}",
                reason=f"http_{resp.status_code}",
            )
        try:
            return resp.json()
        except Exception as exc:
            raise ListingRejected("FoodLink returned a non-JSON body", reason="malformed_response") from exc

    def create_forecast_listing(self, listing: dict) -> dict:
        payload = self.map_to_foodlink_payload(listing)
        body = self._request("POST", self.listing_path, payload)
        return {
            "listing_id": listing.get("listing_id"),
            "status": listing.get("status", "forecast"),
            "mode": self.mode,
            "demo": False,
            "simulated": False,
            "real_foodlink_executed": True,
            "contract_verified": False,
            "note": "Sent to FoodLink using the UNVERIFIED proposed contract. Confirm the field mapping before relying on this.",
            **self.parse_response(body),
        }

    def confirm_listing(self, listing_id: str, *, confirmed_qty: float | None = None, confirmed_by: str | None = None) -> dict:
        path = f"{self.listing_path.rstrip('/')}/{listing_id}/confirm"
        body = self._request("POST", path, {"qty": confirmed_qty, "confirmed_by": confirmed_by})
        return {"listing_id": listing_id, "status": "confirmed", "mode": self.mode, "contract_verified": False, **self.parse_response(body)}

    def withdraw_listing(self, listing_id: str, *, reason: str = "surplus_did_not_materialise") -> dict:
        path = f"{self.listing_path.rstrip('/')}/{listing_id}/withdraw"
        body = self._request("POST", path, {"reason": reason})
        return {"listing_id": listing_id, "status": "withdrawn", "mode": self.mode, "contract_verified": False, **self.parse_response(body)}

    def get_listing_status(self, listing_id: str) -> dict:
        path = f"{self.listing_path.rstrip('/')}/{listing_id}"
        body = self._request("GET", path)
        return {"listing_id": listing_id, "mode": self.mode, **self.parse_response(body)}


__all__ = ["HttpFoodLinkAdapter"]