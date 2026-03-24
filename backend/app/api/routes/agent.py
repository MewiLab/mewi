from fastapi import APIRouter
from app.services.redis_service import redis_service

router = APIRouter()

@router.get("/status/{user_id}", summary="查詢 Agent 目前的即時狀態")
async def get_agent_status(user_id: str):
    status = redis_service.get_agent_status(user_id)
    return {
        "user_id": user_id, 
        "status": status,
        "is_thinking": status == "thinking"
    }