"""
action.py — The creature's body.  Executes actions against Unity via
the AgentBridge HTTP API.

Design decisions:
- The ActionManager never decides *what* to do.  It only knows *how* to
  do things.  The LLM graph decides; this class executes.

- All methods are async because they make HTTP calls to Unity.  The caller
  (graph node or agent) awaits them.

- The class discovers available actions from Unity's /schema endpoint at
  connect time, so it never hardcodes action names.  If Unity adds a
  "Swim" button tomorrow, this class sees it without code changes.

- ActionResult is a typed return instead of raw dicts.  The graph can
  branch on result.success without string-checking.

- The client (httpx.AsyncClient) is injected, not created internally.
  Tests pass a mock client; production passes a real one.  Same class,
  different wiring.
"""

import logging
import httpx
from app.agent.schemas.action import ActionResult, ActionSchema

logger = logging.getLogger(__file__)

class ActionManager:
    """
    The creature's body — translates high-level action intents into
    HTTP calls to Unity's AgentBridge dispatcher.

    Lifecycle:
      1. __init__ with a base URL and optional httpx client
      2. connect() — fetches /schema and /actions, populates the registry
      3. execute() / move() / stop() — called by the graph or agent
      4. close() — tears down the HTTP client

    The connect/close pattern lets the FastAPI lifespan manage the
    lifecycle cleanly:

        async with action_manager:
            ...  # manager is connected and ready
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        client: httpx.AsyncClient | None = None,
        request_timeout: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=request_timeout)
        self._owns_client = client is None  # only close if we created it

        # Populated by connect()
        self._schema: list[ActionSchema] = []
        self._action_names: set[str] = set()
        self._connected: bool = False

    # ─── Lifecycle ───────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Fetch capability schema from Unity.  Call once at startup.
        Returns True if Unity is reachable and schema was loaded.
        """
        try:
            # Try /schema first (our new discovery endpoint)
            schema_loaded = await self._load_schema()

            # Fall back to /actions (the original AgentBridge endpoint)
            if not schema_loaded:
                await self._load_actions_legacy()

            self._connected = True
            logger.info(
                "ActionManager connected: %d actions available",
                len(self._action_names),
            )
            return True

        except httpx.ConnectError:
            logger.error("Cannot reach Unity at %s", self.base_url)
            return False
        except Exception as e:
            logger.error("Connection failed: %s", e)
            return False

    async def close(self) -> None:
        """Tear down the HTTP client if we own it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ─── Public action API ───────────────────────────────────────────────

    async def execute(self, action: str, **kwargs) -> ActionResult:
        """
        Execute a named action against Unity.

        This is the single entry point the graph calls.  It validates
        the action exists, sends it, and returns a typed result.

        Usage:
            result = await body.execute("Sprint", hold=0.3)
            result = await body.execute("Jump")
            result = await body.execute("move", x=0.5, z=1.0, hold=0.2)
        """
        if not self._connected:
            return ActionResult(
                success=False,
                action=action,
                detail="ActionManager not connected. Call connect() first.",
            )

        # Movement is a special case (axis, not button)
        if action == "move":
            return await self._send_move(
                x=kwargs.get("x", 0.0),
                z=kwargs.get("z", 0.0),
                hold=kwargs.get("hold", 0.15),
            )

        if action == "stop":
            return await self._send_action("stop")

        # Validate action exists in registry
        if self._action_names and action not in self._action_names:
            logger.warning("Action '%s' not in registry: %s", action, self._action_names)
            return ActionResult(
                success=False,
                action=action,
                detail=f"Unknown action '{action}'. Available: {sorted(self._action_names)}",
            )

        return await self._send_action(action, hold=kwargs.get("hold", 0.3))

    async def move(self, x: float, z: float, hold: float = 0.15) -> ActionResult:
        """Convenience: send movement axis."""
        return await self.execute("move", x=x, z=z, hold=hold)

    async def stop(self) -> ActionResult:
        """Convenience: stop all movement."""
        return await self.execute("stop")

    async def get_state(self) -> dict[str, Any]:
        """Read current creature state from Unity."""
        try:
            resp = await self._client.get(f"{self.base_url}/state")
            return resp.json()
        except Exception as e:
            logger.error("Failed to read state: %s", e)
            return {"error": str(e)}

    async def get_world(self, name: Optional[str] = None, tag: Optional[str] = None) -> dict:
        """Query Unity scene for objects by name or tag."""
        params = {}
        if name:
            params["name"] = name
        if tag:
            params["tag"] = tag
        try:
            resp = await self._client.get(f"{self.base_url}/world", params=params)
            return resp.json()
        except Exception as e:
            logger.error("World query failed: %s", e)
            return {"objects": [], "error": str(e)}

    async def get_nav(self, target_x: float, target_z: float) -> dict:
        """Query Unity NavMesh for pathfinding direction."""
        try:
            resp = await self._client.get(
                f"{self.base_url}/nav",
                params={"tx": f"{target_x:.2f}", "tz": f"{target_z:.2f}"},
            )
            return resp.json()
        except Exception as e:
            logger.error("Nav query failed: %s", e)
            return {"reachable": False, "error": str(e)}

    # ─── Schema introspection ────────────────────────────────────────────

    @property
    def available_actions(self) -> list[str]:
        """List of action names Unity currently supports."""
        return sorted(self._action_names)

    @property
    def schema(self) -> list[ActionSchema]:
        """Full action schemas with types and descriptions."""
        return list(self._schema)

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_actions_for_prompt(self) -> str:
        """
        Format available actions as a string the LLM can read in its
        system prompt.  E.g.:
          - move(x, z, hold): Move in a direction
          - Sprint(hold): Toggle sprinting
          - Jump(hold): Jump or climb
        """
        if not self._schema:
            return "Actions: " + ", ".join(sorted(self._action_names))

        lines = []
        for s in self._schema:
            params = ", ".join(s.parameters.keys()) if s.parameters else ""
            desc = f" — {s.description}" if s.description else ""
            lines.append(f"  - {s.name}({params}){desc}")
        return "Available actions:\n" + "\n".join(lines)

    # ─── Internal HTTP ───────────────────────────────────────────────────

    async def _send_action(self, action: str, hold: float = 0.3) -> ActionResult:
        """POST a button action to Unity."""
        try:
            resp = await self._client.post(
                f"{self.base_url}/action",
                json={"action": action, "hold": hold},
            )
            data = resp.json()
            return ActionResult(
                success=data.get("ok", False),
                action=action,
                raw_response=data,
            )
        except Exception as e:
            logger.error("Action '%s' failed: %s", action, e)
            return ActionResult(success=False, action=action, detail=str(e))

    async def _send_move(self, x: float, z: float, hold: float = 0.15) -> ActionResult:
        """POST a movement axis command to Unity."""
        try:
            resp = await self._client.post(
                f"{self.base_url}/action",
                json={"action": "move", "x": x, "y": z, "hold": hold},
            )
            data = resp.json()
            return ActionResult(
                success=data.get("ok", False),
                action="move",
                detail=f"axis=({x:.2f}, {z:.2f})",
                raw_response=data,
            )
        except Exception as e:
            logger.error("Move failed: %s", e)
            return ActionResult(success=False, action="move", detail=str(e))

    async def _load_schema(self) -> bool:
        """Try to load the new /schema discovery endpoint."""
        try:
            resp = await self._client.get(f"{self.base_url}/schema")
            if resp.status_code != 200:
                return False

            data = resp.json()
            tools = data.get("tools", [])
            if not tools:
                return False

            self._schema = [
                ActionSchema(
                    name=t["name"],
                    action_type=t.get("type", "button"),
                    description=t.get("description", ""),
                    parameters=t.get("parameters", {}),
                )
                for t in tools
            ]
            self._action_names = {s.name for s in self._schema}
            # Always include built-in actions
            self._action_names.update({"move", "stop", "wait"})
            return True

        except Exception:
            return False

    async def _load_actions_legacy(self) -> None:
        """Fall back to the original /actions endpoint."""
        try:
            resp = await self._client.get(f"{self.base_url}/actions")
            data = resp.json()
            names = data.get("actions", [])
            self._action_names = set(names)
        except Exception as e:
            logger.warning("Legacy /actions fetch failed: %s", e)
            self._action_names = {"move", "stop", "wait"}