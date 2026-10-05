from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis")

from app.repositories.place_memory_cache import PlaceMemoryCache


@pytest.fixture
def cache() -> PlaceMemoryCache:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    return PlaceMemoryCache(redis, ttl_seconds=3600, refresh_seconds=30.0)


async def test_record_visit_increments_only_when_zone_changes(cache: PlaceMemoryCache) -> None:
    await cache.record_visit("cat", "Bamboo", observed_at=1000.0, request_id="r1")
    await cache.record_visit("cat", "Bamboo", observed_at=1005.0, request_id="r2")

    overlay = await cache.load_overlay("cat")
    entry = overlay.get("Bamboo")
    assert entry is not None
    assert entry.visit_count == 1


async def test_record_visit_counts_each_zone_switch(cache: PlaceMemoryCache) -> None:
    await cache.record_visit("cat", "Bamboo", observed_at=1000.0)
    await cache.record_visit("cat", "Harbor", observed_at=1001.0)
    await cache.record_visit("cat", "Bamboo", observed_at=1002.0)

    overlay = await cache.load_overlay("cat")
    assert overlay.get("Bamboo").visit_count == 2
    assert overlay.get("Harbor").visit_count == 1


async def test_record_visit_refreshes_after_throttle_window(cache: PlaceMemoryCache) -> None:
    await cache.record_visit("cat", "Bamboo", observed_at=1000.0, request_id="r1")
    await cache.record_visit("cat", "Bamboo", observed_at=1031.0, request_id="r2")

    overlay = await cache.load_overlay("cat")
    entry = overlay.get("Bamboo")
    assert entry is not None
    assert entry.visit_count == 1
    assert entry.last_visited_at == 1031.0
    assert entry.last_arrival_request_id == "r2"


async def test_load_overlay_skips_meta_field(cache: PlaceMemoryCache) -> None:
    await cache.record_visit("cat", "Bamboo", observed_at=1000.0)

    overlay = await cache.load_overlay("cat")
    assert set(overlay.entries.keys()) == {"Bamboo"}
