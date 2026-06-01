from fastapi import APIRouter, Depends, WebSocket

from app.api.deps import AgentTickServiceDep, verify_api_key
from app.services.agent_tick.ws_session import AgentTickWebSocketSession

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(verify_api_key)])


@router.websocket("/ws")
async def agent_tick_hub_ws(
    websocket: WebSocket,
    service: AgentTickServiceDep,
) -> None:
    """Shared Unity app websocket: one socket, many creature tick jobs."""
    await AgentTickWebSocketSession(websocket, service).run()
