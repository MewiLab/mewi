"""
unity_client.py — HTTP transport to Unity's AgentBridge.

This is the ONLY file that knows about httpx, endpoint URLs, and JSON
wire format.  Everything else in the agent package works with typed
Python objects.

Design decisions:
- Protocol class (UnityClientProtocol) defines the interface.  Any
  transport that implements it works: HTTP now, WebSocket later,
  mock in tests, direct C# interop if you ever embed Python in Unity.

- The HTTP implementation (HttpUnityClient) is a thin async wrapper.
  No business logic.  No filtering.  No threat assessment.  It sends
  bytes and returns dicts.

- Connection lifecycle is explicit: connect() loads the schema,
  close() tears down the client.  Supports async context manager
  for clean usage in FastAPI lifespan.
"""

import logging
import httpx
from typing import Any, Protocol, runtime_checkable
from app.agent.schemas.action_schema import ActionSchema


logger = logging.getLogger(__name__)


# ─── Protocol (interface) ────────────────────────────────────────────────────

@runtime_checkable
class UnityClientProtocol(Protocol):
    """
    Abstract interface for talking to Unity.

    ActionManager depends on this protocol, never on a concrete class.
    Swap implementations without touching any consumer:
      - HttpUnityClient  → production
      - MockUnityClient  → unit tests
      - WsUnityClient    → future WebSocket transport
      - McpUnityClient   → future MCP transport
    """

    async def connect(self) -> bool: ...
    async def close(self) -> None: ...

    async def send_action(self, action: str, hold: float = 0.3,
                          x: float = 0, y: float = 0) -> dict[str, Any]: ...

    async def get_state(self) -> dict[str, Any]: ...
    async def get_world(self, name: str | None = None,
                        tag: str | None = None) -> dict[str, Any]: ...
    async def get_nav(self, target_x: float, target_z: float) -> dict[str, Any]: ...

    @property
    def is_connected(self) -> bool: ...
    @property
    def action_schemas(self) -> list[ActionSchema]: ...
    @property
    def action_names(self) -> set[str]: ...


# ─── HTTP implementation ─────────────────────────────────────────────────────

class HttpUnityClient:
    """
    Concrete HTTP transport to Unity's AgentBridge.

    This class knows:
      - endpoint paths (/action, /state, /schema, /world, /nav)
      - JSON wire format ({"action": ..., "hold": ...})
      - httpx.AsyncClient lifecycle

    This class does NOT know:
      - what actions mean (that's ActionManager)
      - how to filter entities (that's SnapshotManager)
      - what to do with state data (that's the graph)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        client: httpx.AsyncClient | None = None,
        timeout: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

        self._schemas: list[ActionSchema] = []
        self._names: set[str] = set()
        self._connected: bool = False

    # ─── Lifecycle ───────────────────────────────────────────────────────

    async def connect(self) -> bool:
        try:
            loaded = await self._load_schema()
            if not loaded:
                await self._load_actions_legacy()

            self._connected = True
            logger.info(
                "HttpUnityClient connected to %s (%d actions)",
                self.base_url,
                len(self._names),
            )
            return True

        except httpx.ConnectError:
            logger.error("Cannot reach Unity at %s", self.base_url)
            return False
        except Exception as e:
            logger.error("Connection failed: %s", e)
            return False

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        self._connected = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ─── Commands ────────────────────────────────────────────────────────

    async def send_action(
        self,
        action: str,
        hold: float = 0.3,
        x: float = 0,
        y: float = 0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": action, "hold": hold}
        if action == "move":
            payload["x"] = x
            payload["y"] = y

        try:
            resp = await self._client.post(
                f"{self.base_url}/action", json=payload
            )
            return resp.json()
        except Exception as e:
            logger.error("send_action(%s) failed: %s", action, e)
            return {"ok": False, "error": str(e)}

    # ─── Queries ─────────────────────────────────────────────────────────

    async def get_state(self) -> dict[str, Any]:
        try:
            resp = await self._client.get(f"{self.base_url}/state")
            return resp.json()
        except Exception as e:
            logger.error("get_state failed: %s", e)
            return {"error": str(e)}

    async def get_world(
        self,
        name: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {}
        if name:
            params["name"] = name
        if tag:
            params["tag"] = tag
        try:
            resp = await self._client.get(
                f"{self.base_url}/world", params=params
            )
            return resp.json()
        except Exception as e:
            logger.error("get_world failed: %s", e)
            return {"objects": [], "error": str(e)}

    async def get_nav(self, target_x: float, target_z: float) -> dict[str, Any]:
        try:
            resp = await self._client.get(
                f"{self.base_url}/nav",
                params={"tx": f"{target_x:.2f}", "tz": f"{target_z:.2f}"},
            )
            return resp.json()
        except Exception as e:
            logger.error("get_nav failed: %s", e)
            return {"reachable": False, "error": str(e)}

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

    # ─── Schema loading ──────────────────────────────────────────────────

    async def _load_schema(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/schema")
            if resp.status_code != 200:
                return False

            data = resp.json()
            tools = data.get("tools", [])
            if not tools:
                return False

            self._schemas = [
                ActionSchema(
                    name=t["name"],
                    action_type=t.get("type", "button"),
                    description=t.get("description", ""),
                    parameters=t.get("parameters", {}),
                )
                for t in tools
            ]
            self._names = {s.name for s in self._schemas}
            self._names.update({"move", "stop", "wait"})
            return True

        except Exception:
            return False

    async def _load_actions_legacy(self) -> None:
        try:
            resp = await self._client.get(f"{self.base_url}/actions")
            data = resp.json()
            self._names = set(data.get("actions", []))
        except Exception as e:
            logger.warning("Legacy /actions failed: %s", e)
            self._names = {"move", "stop", "wait"}