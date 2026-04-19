"""
Automated schema manager for Supabase.

Reads migration.sql and applies it via the exec_sql RPC tunnel.
Only intended to run in development; guarded in lifespan.py.
"""

import asyncio
import logging
from pathlib import Path

from supabase import AsyncClient

logger = logging.getLogger(__name__)

_SQL_PATH = Path(__file__).parent / "migration.sql"


class SupabaseSchemaManager:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def apply_schema(self) -> None:
        sql = _SQL_PATH.read_text(encoding="utf-8")
        await self._client.rpc("exec_sql", {"query": sql}).execute()

    async def initialize_db(self, retries: int = 5, delay: float = 3.0) -> None:
        logger.info("Applying database schema from %s", _SQL_PATH)
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                await self.apply_schema()
                logger.info("Schema applied successfully")
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Schema apply attempt %d/%d failed: %s", attempt, retries, exc
                )
                if attempt < retries:
                    await asyncio.sleep(delay)
        logger.error("Schema application failed after %d attempts", retries)
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def adapt_unity_payload(payload: dict, mapping: dict) -> dict:
        """Re-key a Unity JSON payload using a column-name mapping."""
        return {mapping.get(k, k): v for k, v in payload.items()}
