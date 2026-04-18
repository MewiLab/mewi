"""
unity_client.py — HTTP transport to Unity's AgentBridge.

The ONE file that knows about httpx, endpoint URLs, and JSON wire format.
Everything above this layer works with typed Python objects only.

─── What AgentBridge.cs actually serves ────────────────────────────────────
    GET  /ping      → {"status": "ok"}
    GET  /state     → GameState JSON (pos, rot, activeState, speed, sprint …)
    GET  /actions   → {"actions": ["move", "stop", "wait", "Jump", …]}
    POST /action    → {"action", "hold", "x"?, "y"?}  ←  {"ok": true}

    /schema, /world, /nav — NOT in AgentBridge.cs yet (honest stubs below).

─── The timing contract you must understand ────────────────────────────────
    AgentBridge.cs dequeues ONE action per Unity Update() frame (~16 ms).
    POST /action returns {"ok":true} the moment the action is ENQUEUED,
    not when it has EXECUTED or FINISHED.

    This means:
      • A move with hold=0.5 runs for 0.5 s on the Unity side.
      • Python gets {"ok":true} in ~1 ms.
      • If you immediately send the next action, Unity is still mid-move.

    HttpUnityClient solves this with execute_sequence():
      Each step waits for its own hold duration before the next POST fires.
      The result is a creature that walks, then jumps, then sprints —
      not a creature that receives three simultaneous conflicting inputs.

─── Sequence timing model ──────────────────────────────────────────────────

    Python timeline:
    t=0.000  POST move(y=1, hold=0.5)  → ok   ← Unity starts moving
    t=0.000  asyncio.sleep(0.5 + gap)
    t=0.550  POST Jump(hold=0.2)       → ok   ← Unity was still moving, now jumps
    t=0.550  asyncio.sleep(0.2 + gap)
    t=0.800  POST Sprint(hold=0.3)     → ok   ← Unity lands, now sprints

    gap (default 0.05 s) absorbs:
      • Unity frame dispatch latency (~16 ms)
      • Network round-trip on localhost (~1 ms)
      • Malbers animation blend time (~20-40 ms)
    Tune it up if actions still overlap; down if the creature feels sluggish.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from app.agent.schemas.action_schema import ActionSchema

logger = logging.getLogger(__name__)

_BUILTIN_ACTIONS: frozenset[str] = frozenset({"move", "stop", "wait"})

# Seconds added after each action's hold before the next action fires.
# Absorbs Unity frame dispatch + Malbers animation blend time.
_DEFAULT_GAP: float = 0.05


# ─── Action step dataclass ────────────────────────────────────────────────────

@dataclass
class ActionStep:
    """
    One step in a creature behaviour sequence.

    Fields:
        action  — name registered in AgentBridge ("move", "Jump", "Sprint" …)
        hold    — how long Unity holds the input, in seconds
                    move:   duration the axis is applied via _moveTimer
                    button: duration between OnInputDown and OnInputUp
        x, y    — axis values for "move" only  (x=strafe, y=forward/back)
        gap     — extra wait AFTER hold before the next step fires
                  None → use the client's default_gap

    Examples:
        ActionStep("move",    hold=0.6, y=1.0)   # walk forward 0.6 s
        ActionStep("Sprint",  hold=0.3)           # sprint burst
        ActionStep("Jump",    hold=0.2)           # jump
        ActionStep("stop")                        # halt immediately
        ActionStep("wait",    gap=1.0)            # pause 1 s, no Unity call
    """
    action: str
    hold:   float        = 0.3
    x:      float        = 0.0
    y:      float        = 0.0
    gap:    float | None = None   # None → use client default_gap


@dataclass
class SequenceResult:
    """Outcome of execute_sequence()."""
    steps:      list[ActionStep]
    results:    list[dict[str, Any]]
    success:    bool
    failed_at:  int | None = None   # index of first failed step, or None
    total_time: float      = 0.0    # wall-clock seconds the sequence took


# ─── Protocol ────────────────────────────────────────────────────────────────

@runtime_checkable
class UnityClientProtocol(Protocol):
    """
    Interface for any Unity transport.

    ActionManager depends on this, never on a concrete class.
    Swap freely:
        HttpUnityClient  — HTTP to AgentBridge.cs  (production)
        MockUnityClient  — in-memory stub           (tests / offline dev)
    """

    async def connect(self) -> bool: ...
    async def close(self)  -> None: ...

    async def send_action(
        self,
        action: str,
        hold:   float = 0.3,
        x:      float = 0.0,
        y:      float = 0.0,
    ) -> dict[str, Any]: ...

    async def execute_sequence(
        self,
        steps:           list[ActionStep],
        stop_on_failure: bool = True,
    ) -> SequenceResult: ...

    async def get_state(self) -> dict[str, Any]: ...
    async def get_world(
        self, name: str | None = None, tag: str | None = None,
    ) -> dict[str, Any]: ...
    async def get_nav(self, target_x: float, target_z: float) -> dict[str, Any]: ...

    @property
    def is_connected(self)   -> bool: ...
    @property
    def action_schemas(self) -> list[ActionSchema]: ...
    @property
    def action_names(self)   -> set[str]: ...


# ─── HTTP implementation ──────────────────────────────────────────────────────

class HttpUnityClient:
    """
    Concrete HTTP transport to AgentBridge.cs.

    Knows:
        endpoint paths, HTTP verbs, JSON wire format, httpx lifecycle,
        action timing and sequencing.

    Does NOT know:
        what actions mean (ActionManager), perception parsing (SnapshotManager),
        which action to choose (graph).
    """

    def __init__(
        self,
        base_url:    str                      = "http://localhost:8080",
        timeout:     float                    = 3.0,
        default_gap: float                    = _DEFAULT_GAP,
        client:      httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url     = base_url.rstrip("/")
        self._timeout     = timeout
        self.default_gap  = default_gap
        self._client      = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

        self._schemas:   list[ActionSchema] = []
        self._names:     set[str]           = set(_BUILTIN_ACTIONS)
        self._connected: bool               = False

    # ─── Lifecycle ────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Ping Unity first (loud failure), then load real action names."""
        try:
            if not await self._ping():
                logger.error(
                    "AgentBridge not reachable at %s "
                    "(is Unity in Play mode with AgentBridge attached?)",
                    self.base_url,
                )
                return False

            await self._load_actions()
            self._connected = True
            logger.info(
                "Connected to AgentBridge at %s  (%d actions: %s)",
                self.base_url, len(self._names), sorted(self._names),
            )
            return True

        except httpx.ConnectError:
            logger.error("Connection refused at %s", self.base_url)
            return False
        except Exception as exc:
            logger.error("connect() failed: %s", exc)
            return False

    async def close(self) -> None:
        self._connected = False
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "HttpUnityClient":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ─── Single action ────────────────────────────────────────────────────

    async def send_action(
        self,
        action: str,
        hold:   float = 0.3,
        x:      float = 0.0,
        y:      float = 0.0,
    ) -> dict[str, Any]:
        """
        POST /action — enqueue ONE action in AgentBridge and return immediately.

        Returns {"ok": true} when enqueued, NOT when Unity finishes executing.
        Call execute_sequence() when ordering matters.

        Wire format AgentBridge.cs expects:
            button:  {"action": "Jump",  "hold": 0.2}
            move:    {"action": "move",  "hold": 0.5, "x": 0.0, "y": 1.0}
            stop:    {"action": "stop",  "hold": 0.0}
        """
        payload: dict[str, Any] = {"action": action, "hold": hold}
        if action == "move":
            payload["x"] = x
            payload["y"] = y   # AgentBridge: y = forward/back axis

        try:
            resp = await self._client.post(
                f"{self.base_url}/action", json=payload,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("send_action(%s) failed: %s", action, exc)
            return {"ok": False, "error": str(exc)}

    # ─── Sequence execution ───────────────────────────────────────────────

    async def execute_sequence(
        self,
        steps:           list[ActionStep],
        stop_on_failure: bool = True,
    ) -> SequenceResult:
        """
        Execute a list of ActionSteps in order, respecting Unity timing.

        For each step:
            1. POST the action to AgentBridge.
            2. Sleep  hold + gap  before sending the next step.

        Why the sleep matters
        ─────────────────────
        AgentBridge.cs dequeues one action per frame and runs it for `hold`
        seconds on the Unity side.  Python's POST returns immediately after
        enqueueing — it has NO idea when the action actually finishes.

        Without the sleep you get race conditions:
            POST move(hold=0.5)   ← Unity starts moving
            POST Jump immediately ← Unity is mid-move, jump fires at wrong time
            POST Sprint           ← all three collide, cat twitches randomly

        With the sleep you get sequenced behaviour:
            POST move(hold=0.5) → sleep 0.55 s → POST Jump → sleep 0.25 s → ...

        Special cases:
            "wait"  — skips the POST, sleeps for `gap` only (a pure pause)
            "stop"  — POSTed normally but hold is ignored in sleep (gap only)

        Args:
            steps:           ordered list of ActionStep
            stop_on_failure: abort on first failed POST (default True)

        Returns:
            SequenceResult — per-step results, success flag, total wall time.

        Usage examples:

            # Walk forward, then jump
            await client.execute_sequence([
                ActionStep("move",  hold=0.6, y=1.0),
                ActionStep("Jump",  hold=0.2),
                ActionStep("stop"),
            ])

            # Sprint attack combo
            await client.execute_sequence([
                ActionStep("Sprint",  hold=0.1),
                ActionStep("move",    hold=0.4, y=1.0),
                ActionStep("Attack1", hold=0.2),
                ActionStep("stop"),
            ])

            # Patrol loop: walk, pause, look, walk back
            await client.execute_sequence([
                ActionStep("move", hold=1.0, y=1.0),
                ActionStep("wait", gap=0.5),
                ActionStep("move", hold=1.0, y=-1.0),
                ActionStep("stop"),
            ])
        """
        t_start:   float                 = time.monotonic()
        results:   list[dict[str, Any]]  = []
        failed_at: int | None            = None

        for i, step in enumerate(steps):
            gap = step.gap if step.gap is not None else self.default_gap

            # ── "wait" → no POST, just pause ─────────────────────────────
            if step.action == "wait":
                logger.debug("Sequence step %d: wait %.2fs", i, gap)
                await asyncio.sleep(gap)
                results.append({"ok": True, "action": "wait"})
                continue

            logger.debug(
                "Sequence step %d: %s  hold=%.2f  x=%.2f  y=%.2f",
                i, step.action, step.hold, step.x, step.y,
            )

            result = await self.send_action(
                step.action, hold=step.hold, x=step.x, y=step.y,
            )
            results.append(result)

            if not result.get("ok", False):
                logger.warning(
                    "Sequence step %d failed: %s — %s",
                    i, step.action, result.get("error", "unknown"),
                )
                failed_at = i
                if stop_on_failure:
                    break

            # ── Timing wait ───────────────────────────────────────────────
            # "stop" has no meaningful hold duration — gap alone is enough.
            wait = (0.0 if step.action == "stop" else step.hold) + gap
            await asyncio.sleep(wait)

        return SequenceResult(
            steps=steps,
            results=results,
            success=failed_at is None,
            failed_at=failed_at,
            total_time=time.monotonic() - t_start,
        )

    # ─── Queries ──────────────────────────────────────────────────────────

    async def get_state(self) -> dict[str, Any]:
        """
        GET /state → GameState
            posX, posY, posZ, rotY,
            activeState, activeStance, grounded,
            speed, sprint, moveX, moveY
        """
        try:
            resp = await self._client.get(f"{self.base_url}/state")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("get_state failed: %s", exc)
            return {"error": str(exc)}

    async def get_world(
        self,
        name: str | None = None,
        tag:  str | None = None,
    ) -> dict[str, Any]:
        """Stub — /world not in AgentBridge.cs yet."""
        logger.debug("get_world: not implemented in AgentBridge.cs")
        return {"objects": [], "error": "not implemented in AgentBridge"}

    async def get_nav(self, target_x: float, target_z: float) -> dict[str, Any]:
        """Stub — /nav not in AgentBridge.cs yet."""
        logger.debug("get_nav: not implemented in AgentBridge.cs")
        return {"reachable": False, "error": "not implemented in AgentBridge"}

    # ─── Properties ───────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def action_schemas(self) -> list[ActionSchema]:
        return list(self._schemas)

    @property
    def action_names(self) -> set[str]:
        return set(self._names)

    # ─── Internal helpers ─────────────────────────────────────────────────

    async def _ping(self) -> bool:
        """GET /ping → {"status": "ok"}"""
        try:
            resp = await self._client.get(f"{self.base_url}/ping")
            return resp.status_code == 200 and resp.json().get("status") == "ok"
        except Exception:
            return False

    async def _load_actions(self) -> None:
        """
        GET /actions → {"actions": [...]}

        Populates _names (validation set) and _schemas (synthesised metadata).
        AgentBridge does not serve rich schema data, so action types and
        parameters are inferred from the name only.
        """
        try:
            resp = await self._client.get(f"{self.base_url}/actions")
            resp.raise_for_status()
            names: list[str] = resp.json().get("actions", [])

            self._names = set(names) | _BUILTIN_ACTIONS
            self._schemas = [
                ActionSchema(
                    name=n,
                    action_type="axis" if n in ("move", "stop") else "button",
                    description="",
                    parameters=(
                        {"x": "float", "y": "float", "hold": "float"} if n == "move"
                        else {"hold": "float"} if n not in ("stop", "wait")
                        else {}
                    ),
                )
                for n in sorted(self._names)
            ]
            logger.debug(
                "Loaded %d actions: %s", len(self._names), sorted(self._names),
            )

        except Exception as exc:
            logger.warning("_load_actions failed (%s) — builtins only", exc)
            self._names   = set(_BUILTIN_ACTIONS)
            self._schemas = []