import json

import pytest

from app.core.config import Settings
from app.services.agent_tick.tick_service import (
    AGENT_TICK_SCHEMA,
    IN_FLIGHT_KEY,
    JOB_QUEUE_KEY,
    AgentTickInFlightError,
    AgentTickService,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
                self.values.pop(key, None)
            if key in self.lists:
                deleted += 1
                self.lists.pop(key, None)
        return deleted

    async def rpush(self, key: str, *values: str) -> int:
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    async def blpop(self, key: str, timeout: int = 0):
        items = self.lists.get(key) or []
        if not items:
            return None
        return key, items.pop(0)

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        key = keys_and_args[0]
        expected_request_id = keys_and_args[numkeys]
        raw = self.values.get(key)
        if raw is None:
            return 0
        try:
            current_request_id = str(json.loads(raw).get("request_id") or "")
        except json.JSONDecodeError:
            current_request_id = raw
        if current_request_id != expected_request_id:
            return 0
        self.values.pop(key, None)
        return 1


@pytest.fixture
def tick_service() -> tuple[AgentTickService, FakeRedis]:
    redis = FakeRedis()
    settings = Settings(
        supabase_url="http://fake-supabase",
        supabase_publishable_key="fake-anon-key",
        supabase_secret_key="fake-secret-key",
        openai_api_key="fake-openai-key",
        agent_status_ttl=60,
    )
    return AgentTickService(redis=redis, settings=settings), redis


async def test_submit_tick_writes_v2_job_and_in_flight_reservation(tick_service):
    service, redis = tick_service

    accepted = await service.submit_tick("cat_a", {"requestId": "req-001", "self": {}})
    queued = await service.get_next_job(timeout=0)
    stored = await service.get_job(accepted["job_id"])
    in_flight = await service.get_in_flight("cat_a")

    assert accepted["schema"] == AGENT_TICK_SCHEMA
    assert accepted["creature_id"] == "cat_a"
    assert accepted["request_id"] == "req-001"
    assert queued["schema"] == AGENT_TICK_SCHEMA
    assert queued["type"] == "agent_tick"
    assert queued["job_id"] == accepted["job_id"]
    assert stored["payload"]["requestId"] == "req-001"
    assert in_flight["request_id"] == "req-001"
    assert json.loads(redis.values[IN_FLIGHT_KEY.format(creature_id="cat_a")])["job_id"] == accepted["job_id"]
    assert redis.lists[JOB_QUEUE_KEY] == []


async def test_submit_tick_rejects_same_creature_when_in_flight(tick_service):
    service, _redis = tick_service

    await service.submit_tick("cat_a", {"requestId": "req-001", "self": {}})

    with pytest.raises(AgentTickInFlightError) as exc:
        await service.submit_tick("cat_a", {"requestId": "req-002", "self": {}})

    assert exc.value.creature_id == "cat_a"
    assert exc.value.request_id == "req-002"
    assert exc.value.existing_request_id == "req-001"


async def test_submit_tick_allows_different_creatures_in_flight(tick_service):
    service, _redis = tick_service

    cat_a = await service.submit_tick("cat_a", {"requestId": "req-a", "self": {}})
    cat_b = await service.submit_tick("cat_b", {"requestId": "req-b", "self": {}})

    assert cat_a["creature_id"] == "cat_a"
    assert cat_b["creature_id"] == "cat_b"
    assert (await service.get_in_flight("cat_a"))["request_id"] == "req-a"
    assert (await service.get_in_flight("cat_b"))["request_id"] == "req-b"


async def test_publish_result_releases_in_flight_for_matching_request(tick_service):
    service, _redis = tick_service
    accepted = await service.submit_tick("cat_a", {"requestId": "req-001", "self": {}})

    await service.publish_result(
        "cat_a",
        accepted["job_id"],
        {"request_id": "req-001", "intent": {"intent": "EXPLORE"}},
    )

    assert await service.get_in_flight("cat_a") is None
    accepted_next = await service.submit_tick("cat_a", {"requestId": "req-002", "self": {}})
    assert accepted_next["request_id"] == "req-002"


async def test_publish_result_does_not_release_newer_in_flight_request(tick_service):
    service, _redis = tick_service
    stale = await service.submit_tick("cat_a", {"requestId": "req-001", "self": {}})
    await service.release_in_flight("cat_a", "req-001")
    current = await service.submit_tick("cat_a", {"requestId": "req-002", "self": {}})

    await service.publish_result(
        "cat_a",
        stale["job_id"],
        {"request_id": "req-001", "intent": {"intent": "EXPLORE"}},
    )

    in_flight = await service.get_in_flight("cat_a")
    assert current["request_id"] == "req-002"
    assert in_flight["request_id"] == "req-002"
    assert in_flight["job_id"] == current["job_id"]


async def test_publish_error_releases_in_flight(tick_service):
    service, _redis = tick_service
    accepted = await service.submit_tick("cat_a", {"requestId": "req-001", "self": {}})

    await service.publish_error("cat_a", accepted["job_id"], "boom")

    assert await service.get_in_flight("cat_a") is None
