from __future__ import annotations

import logging
from typing import Any

from app.agent.schemas.place_memory_schema import PlaceMemoryOverlay

logger = logging.getLogger(__name__)


class PlaceMemoryStoreChain:
    """Writes place memory to multiple stores and reads from the first durable one."""

    def __init__(self, *stores: Any) -> None:
        self._stores = [store for store in stores if store is not None]

    async def record_visit(
        self,
        creature_id: str,
        zone_id: str,
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None:
        for store in self._stores:
            if not hasattr(store, "record_visit"):
                continue
            try:
                await store.record_visit(
                    creature_id,
                    zone_id,
                    observed_at=observed_at,
                    request_id=request_id,
                )
            except Exception:
                logger.warning(
                    "Place memory visit write failed store=%s creature_id=%s zone_id=%s",
                    type(store).__name__,
                    creature_id,
                    zone_id,
                    exc_info=True,
                )

    async def record_seen_places(
        self,
        creature_id: str,
        zone_ids: list[str],
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None:
        for store in self._stores:
            if not hasattr(store, "record_seen_places"):
                continue
            try:
                await store.record_seen_places(
                    creature_id,
                    zone_ids,
                    observed_at=observed_at,
                    request_id=request_id,
                )
            except Exception:
                logger.warning(
                    "Place memory seen write failed store=%s creature_id=%s",
                    type(store).__name__,
                    creature_id,
                    exc_info=True,
                )

    async def load_overlay(self, creature_id: str) -> PlaceMemoryOverlay:
        for store in reversed(self._stores):
            if not hasattr(store, "load_overlay"):
                continue
            try:
                overlay = await store.load_overlay(creature_id)
            except Exception:
                logger.warning(
                    "Place memory overlay read failed store=%s creature_id=%s",
                    type(store).__name__,
                    creature_id,
                    exc_info=True,
                )
                continue
            if overlay.entries:
                return overlay
        return PlaceMemoryOverlay()
