import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

def test_supabase_connection():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("❌ 錯誤：找不到 SUPABASE_URL 或 SUPABASE_KEY，請檢查 .env 檔案！")
        return

    try:
        supabase = create_client(url, key)
        
        response = supabase.table("users").select("*").limit(1).execute()
        
        print("✅ [連線成功] 你的 FastAPI 已經成功握手 Supabase！")
        print(f"🔗 連線網址: {url}")
        
    except Exception as e:
        print(f"❌ [連線失敗] 發生錯誤：{e}")

if __name__ == "__main__":
    test_supabase_connection()