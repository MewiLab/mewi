from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from typing import List
from uuid import UUID
from backend.app.db.models import MicrologSchema
from app.repositories.microlog_repository import MicrologRepository
from app.services.agent_memory_service import AgentMemoryService
from app.services.redis_service import redis_service
import asyncio

router = APIRouter()

async def agent_thinking_event(log_id: str, user_id: str, content: str):
    # TODO 後來的回覆將改成OPENAI回答
    try:
        # 標記 Agent 正在思考
        redis_service.set_agent_status(user_id, "thinking")
        
        # 模擬 AI 運算延遲
        await asyncio.sleep(3) 
        reply = f"喵～聽起來你今天過得不錯：{content[:10]}..." 
        
        # 更新 Supabase 中的回覆內容
        MicrologRepository.update_microlog_reply(log_id, reply)
        
        # 恢復閒置狀態
        redis_service.set_agent_status(user_id, "idle")
    except Exception as e:
        print(f"Agent Thinking Error: {e}")
        # 出錯時也要確保狀態恢復，避免 Unity 端的貓咪一直抓頭
        redis_service.set_agent_status(user_id, "idle")

@router.get("/{user_id}", response_model=List[MicrologSchema])
async def get_logs(user_id: UUID, count: int = Query(10, ge=1, le=100)):
    """獲取特定使用者的歷史紀錄"""
    return MicrologRepository.get_user_logs(str(user_id), limit=count)

@router.post("/")
async def create_log(log_data: MicrologSchema, background_tasks: BackgroundTasks):
    """新增日記紀錄並觸發 Agent 思考事件"""
    try:
        processed = AgentMemoryService.process_new_microlog(log_data) # 處理內容 (向量化)
        
        result = MicrologRepository.create_microlog(processed) # 存入 Supabase 資料庫
        
        new_log_id = result[0]['id'] # 取得新產生的 Log ID
        
        # 觸發背景事件
        background_tasks.add_task(
            agent_thinking_event, 
            new_log_id, 
            str(log_data.userId), 
            log_data.content
        )
        
        return {"status": "success", "data": result}
    except Exception as e:
        print(f"Create Log Error: {e}")
        raise HTTPException(status_code=400, detail=str(e))