"""
action.py — The creature's body.  Pure action logic, no HTTP.

Depends on UnityClientProtocol, never on httpx, URLs, or JSON wire format.
The transport is injected.

    Production:  ActionManager(client=HttpUnityClient("localhost:8080"))
    Tests:       ActionManager(client=MockUnityClient())
"""

import logging
from typing import Any

from app.agent.unity_client import UnityClientProtocol, ActionStep, SequenceResult
from app.agent.schemas.action_schema import ActionResult, ActionSchema

logger = logging.getLogger(__name__)


class ActionManager:
    """
    The creature's body — validates and routes action intents through
    an injected Unity client.

    Two execution modes:

        execute(action, **kwargs)
            Single action, fire-and-forget.  The graph uses this for
            one-shot decisions ("Jump", "move forward for 0.3 s").

        execute_sequence(steps)
            Ordered list of ActionSteps, each waiting for the previous
            to finish before firing.  Use this when the graph produces
            a behaviour — "sprint-attack", "patrol", "flee".

    Responsibilities:
        - Validate actions against the registry before sending
        - Route move (axis) vs button (press/release) correctly
        - Format the action list for LLM consumption
        - Delegate all I/O and timing to the injected client

    NOT responsible for:
        - HTTP, WebSocket, or any transport concern
        - Deciding which action to take (that's the graph)
        - Parsing Unity responses into perception (that's the eye)
    """

    def __init__(self, client: UnityClientProtocol) -> None:
        self._client = client

    # ─── Lifecycle ────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        return await self._client.connect()

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.close()

    # ─── Single action ────────────────────────────────────────────────────

    async def execute(self, action: str, **kwargs) -> ActionResult:
        """
        Single entry point for one-shot actions.

        Validates, routes, executes, returns typed result.
        The graph calls this; it never calls the client directly.

        Does NOT wait for Unity to finish the action — use execute_sequence
        when you need ordered, non-overlapping steps.
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
                y=kwargs.get("y", 0.0),
                hold=kwargs.get("hold", 0.3),
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

    # ─── Sequence execution ───────────────────────────────────────────────

    async def execute_sequence(
        self,
        steps:           list[ActionStep],
        stop_on_failure: bool = True,
    ) -> SequenceResult:
        """
        Execute an ordered behaviour sequence on the creature.

        Each step fires only after the previous step's hold time has elapsed,
        preventing overlapping inputs in Unity.

        The graph should use this when it wants a multi-step behaviour:

            # Walk then jump
            await body.execute_sequence([
                ActionStep("move",  hold=0.6, y=1.0),
                ActionStep("Jump",  hold=0.2),
                ActionStep("stop"),
            ])

            # Sprint-attack combo
            await body.execute_sequence([
                ActionStep("Sprint",  hold=0.1),
                ActionStep("move",    hold=0.4, y=1.0),
                ActionStep("Attack1", hold=0.2),
                ActionStep("stop"),
            ])

            # Patrol: forward, pause, back
            await body.execute_sequence([
                ActionStep("move", hold=1.0, y=1.0),
                ActionStep("wait", gap=0.5),
                ActionStep("move", hold=1.0, y=-1.0),
                ActionStep("stop"),
            ])

        Validates steps before executing: any unknown action name triggers
        an early return with success=False and failed_at set.

        Args:
            steps:           ordered list of ActionStep
            stop_on_failure: abort on first failed step (default True)

        Returns:
            SequenceResult — per-step results, success flag, total wall time.
        """
        if not self._client.is_connected:
            return SequenceResult(
                steps=steps,
                results=[],
                success=False,
                failed_at=0,
                total_time=0.0,
            )

        # Validate all step names upfront so the creature doesn't start
        # a sequence it can't finish.
        known = self._client.action_names
        if known:
            for i, step in enumerate(steps):
                if step.action not in known and step.action not in ("wait",):
                    logger.warning(
                        "execute_sequence: unknown action '%s' at step %d — aborting",
                        step.action, i,
                    )
                    return SequenceResult(
                        steps=steps,
                        results=[],
                        success=False,
                        failed_at=i,
                        total_time=0.0,
                    )

        return await self._client.execute_sequence(
            steps, stop_on_failure=stop_on_failure,
        )

    # ─── Convenience shorthands ───────────────────────────────────────────

    async def move(self, x: float, z: float, hold: float = 0.3) -> ActionResult:
        return await self.execute("move", x=x, z=z, hold=hold)

    async def stop(self) -> ActionResult:
        return await self.execute("stop")

    # ─── World queries ────────────────────────────────────────────────────

    async def get_state(self) -> dict[str, Any]:
        return await self._client.get_state()

    async def get_world(self, name: str | None = None, tag: str | None = None) -> dict:
        return await self._client.get_world(name=name, tag=tag)

    async def get_nav(self, target_x: float, target_y: float) -> dict:
        return await self._client.get_nav(target_x, target_y)

    # ─── Schema introspection ─────────────────────────────────────────────

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
            desc   = f" — {s.description}" if s.description else ""
            lines.append(f"  - {s.name}({params}){desc}")
        return "Available actions:\n" + "\n".join(lines)

    # ─── Internal routing ─────────────────────────────────────────────────

    async def _execute_simple(self, action: str, hold: float = 0.3) -> ActionResult:
        data = await self._client.send_action(action, hold=hold)
        return ActionResult(
            success=data.get("ok", False),
            action=action,
            raw_response=data,
        )

    async def _execute_move(self, x: float, y: float, hold: float) -> ActionResult:
        data = await self._client.send_action("move", hold=hold, x=x, y=y)
        return ActionResult(
            success=data.get("ok", False),
            action="move",
            detail=f"axis=({x:.2f}, {y:.2f})",
            raw_response=data,
        )