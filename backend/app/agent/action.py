"""
action.py — The creature's body.  Pure action logic, no HTTP.

This class depends on UnityClientProtocol, never on httpx, URLs, or
JSON wire format.  The transport is injected.

    Production:  ActionManager(client=HttpUnityClient("localhost:8080"))
    Tests:       ActionManager(client=MockUnityClient())
    Future:      ActionManager(client=McpUnityClient(server))
"""

import logging
from typing import Any

from app.agent.unity_client import UnityClientProtocol
from app.agent.schemas.action import ActionResult, ActionSchema

logger = logging.getLogger(__name__)

# ─── Manager ─────────────────────────────────────────────────────────────────

class ActionManager:
    """
    The creature's body — validates and routes action intents through
    an injected Unity client.

    Responsibilities:
      - Validate that an action exists in the registry before sending
      - Route movement (axis) vs button (press/release) correctly
      - Format the action list for LLM consumption
      - Delegate all I/O to the injected client

    NOT responsible for:
      - HTTP, WebSocket, or any transport concern
      - Deciding which action to take (that's the graph)
      - Parsing Unity responses into perception (that's the eye)
    """

    def __init__(self, client: UnityClientProtocol):
        self._client = client

    # ─── Lifecycle (delegated to client) ─────────────────────────────────

    async def connect(self) -> bool:
        return await self._client.connect()

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ─── Action execution ────────────────────────────────────────────────

    async def execute(self, action: str, **kwargs) -> ActionResult:
        """
        Single entry point for all actions.

        Validates, routes, executes, returns typed result.
        The graph calls this; it never calls the client directly.
        """
        if not self._client.is_connected:
            return ActionResult(
                success=False,
                action=action,
                detail="Not connected. Call connect() first.",
            )

        if action == "move":
            return await self._execute_move(
                x=kwargs.get("x", 0.0),
                z=kwargs.get("z", 0.0),
                hold=kwargs.get("hold", 0.15),
            )

        if action == "stop":
            return await self._execute_simple("stop")

        if action == "wait":
            return ActionResult(success=True, action="wait", detail="Intentional pause")

        # Validate against registry
        known = self._client.action_names
        if known and action not in known:
            return ActionResult(
                success=False,
                action=action,
                detail=f"Unknown action '{action}'. Available: {sorted(known)}",
            )

        return await self._execute_simple(action, hold=kwargs.get("hold", 0.3))

    async def move(self, x: float, z: float, hold: float = 0.15) -> ActionResult:
        return await self.execute("move", x=x, z=z, hold=hold)

    async def stop(self) -> ActionResult:
        return await self.execute("stop")

    # ─── World queries (delegated to client) ─────────────────────────────

    async def get_state(self) -> dict[str, Any]:
        return await self._client.get_state()

    async def get_world(self, name: str | None = None, tag: str | None = None) -> dict:
        return await self._client.get_world(name=name, tag=tag)

    async def get_nav(self, target_x: float, target_z: float) -> dict:
        return await self._client.get_nav(target_x, target_z)

    # ─── Schema introspection ────────────────────────────────────────────

    @property
    def available_actions(self) -> list[str]:
        return sorted(self._client.action_names)

    @property
    def schema(self) -> list[ActionSchema]:
        return self._client.action_schemas

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    def get_actions_for_prompt(self) -> str:
        """Format available actions as LLM-readable text."""
        schemas = self._client.action_schemas
        if not schemas:
            return "Actions: " + ", ".join(sorted(self._client.action_names))

        lines = []
        for s in schemas:
            params = ", ".join(s.parameters.keys()) if s.parameters else ""
            desc = f" — {s.description}" if s.description else ""
            lines.append(f"  - {s.name}({params}){desc}")
        return "Available actions:\n" + "\n".join(lines)

    # ─── Internal routing ────────────────────────────────────────────────

    async def _execute_simple(self, action: str, hold: float = 0.3) -> ActionResult:
        data = await self._client.send_action(action, hold=hold)
        return ActionResult(
            success=data.get("ok", False),
            action=action,
            raw_response=data,
        )

    async def _execute_move(self, x: float, z: float, hold: float) -> ActionResult:
        data = await self._client.send_action("move", hold=hold, x=x, y=z)
        return ActionResult(
            success=data.get("ok", False),
            action="move",
            detail=f"axis=({x:.2f}, {z:.2f})",
            raw_response=data,
        )