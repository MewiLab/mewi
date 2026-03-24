import redis
import os
import json
from dotenv import load_dotenv

load_dotenv()

class RedisService:
    def __init__(self):
        # 建立 Connection Pool
        self.pool = redis.ConnectionPool(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=os.getenv("REDIS_PORT", 6379),
            db=0,
            decode_responses=True # 自動將 bytes 轉成字串
        )
        self.r = redis.Redis(connection_pool=self.pool)

    def set_agent_status(self, user_id: str, status: str):
        self.r.set(f"agent_status:{user_id}", status, ex=300)  # 300後無回應過期

    def get_agent_status(self, user_id: str):
        return self.r.get(f"agent_status:{user_id}") or "idle"

redis_service = RedisService()