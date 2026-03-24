from fastapi.encoders import jsonable_encoder
from app.db.base import supabase
from app.db.models import MicrologSchema
from typing import List, Dict, Any
from postgrest.exceptions import APIError

class MicrologRepository:
    """Repository for managing Microlog entities (Independent Table)"""
    
    @staticmethod
    def create_microlog(data: MicrologSchema) -> List[Dict[str, Any]]:
        # transform Pydantic to Dict
        log_data = data.model_dump(by_alias=True, exclude_none=True)
        
        # transform data before insert
        json_ready_data = jsonable_encoder(log_data)
        
        try:
            response = supabase.table("micrologs").insert(json_ready_data).execute()
            
            return response.data
            
        except APIError as e:
            raise Exception(f"Supabase 寫入錯誤: {e.message}")
        except Exception as e:
            raise Exception(f"未知的存檔失敗: {str(e)}")

    @staticmethod
    def get_user_logs(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        response = supabase.table("micrologs") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        
        return jsonable_encoder(response.data)