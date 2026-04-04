"""
mock_unity_client.py — Test double for UnityClientProtocol.

Lives in tests/, not in app/.  Production code never imports this.

Usage:
    client = MockUnityClient()
    client.set_state({"posX": 10, "posY": 0, "posZ": 5})
    client.add_action("Sprint", "toggle", "Hold to run")

    agent = CreatureAgent(
        eye=SnapshotManager(),
        memory=MemoryManager(),
        body=ActionManager(client=client),
    )
"""

from dataclasses import dataclass, field
from typing import Any

from app.agent.schemas.action import ActionSchema


class MockUnityClient:
    """
    In-memory fake that records every action sent and returns
    configurable responses.  No network, no httpx, instant.
    """

    def __init__(self):
        self._connected: bool = False
        self._schemas: list[ActionSchema] = []
        self._names: set[str] = {"move", "stop", "wait"}

        # Configurable responses
        self._state: dict[str, Any] = {}
        self._world: dict[str, Any] = {"objects": [], "count": 0}
        self._nav: dict[str, Any] = {"reachable": True, "dirX": 0, "dirZ": 1, "distance": 5.0}

        # Action recording — tests assert on this
        self.action_log: list[dict[str, Any]] = []

    # ─── Lifecycle ───────────────────────────────────────────────────────

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def close(self) -> None:
        self._connected = False

    # ─── Commands ────────────────────────────────────────────────────────

    async def send_action(
        self,
        action: str,
        hold: float = 0.3,
        x: float = 0,
        y: float = 0,
    ) -> dict[str, Any]:
        self.action_log.append({
            "action": action, "hold": hold, "x": x, "y": y
        })
        return {"ok": True}

    # ─── Queries ─────────────────────────────────────────────────────────

    async def get_state(self) -> dict[str, Any]:
        return dict(self._state)

    async def get_world(
        self,
        name: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        return dict(self._world)

    async def get_nav(self, target_x: float, target_z: float) -> dict[str, Any]:
        return dict(self._nav)

    # ─── Properties ──────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def action_schemas(self) -> list[ActionSchema]:
        return list(self._schemas)

    @property
    def action_names(self) -> set[str]:
        return set(self._names)

    # ─── Test helpers (not part of the protocol) ─────────────────────────

    def set_state(self, state: dict[str, Any]) -> None:
        self._state = state

    def set_world(self, world: dict[str, Any]) -> None:
        self._world = world

    def set_nav(self, nav: dict[str, Any]) -> None:
        self._nav = nav

    def add_action(self, name: str, action_type: str = "button", description: str = "") -> None:
        self._schemas.append(ActionSchema(name=name, action_type=action_type, description=description))
        self._names.add(name)

    def reset_log(self) -> None:
        self.action_log.clear()

    @property
    def last_action(self) -> dict[str, Any] | None:
        return self.action_log[-1] if self.action_log else None