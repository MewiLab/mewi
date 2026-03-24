import json
import os
import logging
import uuid
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI
from backend.app.db.models import MicrologSchema
from fastapi import UploadFile
from app.db.base import supabase

logger = logging.getLogger(__name__)

MOCK_DATA_PATH = os.path.join(os.path.dirname(__file__), "mock_data/test_sample.json")

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_api_key)

async def get_scent_samples(count: int, category: str, mode: str):
    with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        all_data = json.load(f)
    
    # 找出符合類別跟模式的資料
    filtered = [
        item for item in all_data 
        if item["routing_label"].lower() == category.lower() 
        and item["mode"].lower() == mode.lower()
    ]
    
    # 如果過濾完沒東西，就隨機回傳一筆保險
    result = filtered if filtered else all_data
    return result[:count]


class AgentMemoryService:
    @staticmethod
    def process_new_microlog(log_data: MicrologSchema) -> MicrologSchema:
        """
        將微日記的文字內容轉為 1536 維向量座標。
        """
        # 如果沒有文字內容，就直接回傳，不浪費 API 費用
        if not log_data.content or not log_data.content.strip():
            logger.warning("沒有收到日記內容，跳過 Embedding 處理。")
            return log_data
            
        try:
            # 呼叫 OpenAI 的 Embedding 模型
            response = client.embeddings.create(
                input=log_data.content,
                model="text-embedding-3-small"
            )
            
            # 將拿到的向量塞回 Pydantic 模型裡
            log_data.embedding = response.data[0].embedding
            logger.info("✅ 成功將微日記轉換為 1536 維向量座標！")
            
            return log_data
            
        except Exception as e:
            logger.error(f"OpenAI 向量生成失敗: {str(e)}")
            raise Exception(f"OpenAI 向量生成失敗: {str(e)}")
        
class StorageService:
    """處理實體檔案上傳的服務 (對接 Supabase Storage)"""
    BUCKET_NAME = "micrologs-media"
    @classmethod
    async def upload_file(cls, user_id: str, file: UploadFile, media_type: str) -> str:
        """
        泛用上傳器：自動將檔案分類到 /images, /videos, /voices 資料夾
        """
        try:
            file_bytes = await file.read()
            file_extension = file.filename.split(".")[-1]
            unique_filename = f"{user_id}/{media_type}s/{uuid.uuid4()}.{file_extension}"
            supabase.storage.from_(cls.BUCKET_NAME).upload(
                file=file_bytes,
                path=unique_filename,
                file_options={"content-type": file.content_type}
            )
            public_url = supabase.storage.from_(cls.BUCKET_NAME).get_public_url(unique_filename)
            return public_url
            
        except Exception as e:
            raise Exception(f"{media_type} 上傳至 Supabase 失敗: {str(e)}")