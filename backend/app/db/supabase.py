import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

class SupabaseManager:
    """單例模式：確保整個後端只會有一個 Supabase Client 實例"""
    _instance: Client = None

    @classmethod
    def get_client(cls) -> Client:
        if cls._instance is None:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            if not url or not key:
                raise ValueError("Environment variables SUPABASE_URL or SUPABASE_KEY are missing.")
            
            cls._instance = create_client(url, key)
        return cls._instance

supabase = SupabaseManager.get_client()