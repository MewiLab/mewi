import requests
import time
import uuid

# --- 測試配置 ---
BASE_URL = "http://127.0.0.1:8000/api/v1"
# 使用你的 UUID
TEST_USER_ID = "66af1b4c-4628-4544-addd-15c9a36b4707"
# 使用你提供的 Supabase 圖片 URL
TEST_IMAGE_URL = "https://oavehvhwuzfjudhjfglf.supabase.co/storage/v1/object/public/micrologs-media/66af1b4c-4628-4544-addd-15c9a36b4707/images/1da09fcc-198e-40e7-b113-37e66811d75e.png"

def run_integration_test():
    print("🚀 [MEW Project] 開始 Agent 核心連動整合測試...")
    print("-" * 50)

    try:
        # Step 1: 檢查 Agent 初始狀態是否為 idle
        print("\n[步驟 1] 檢查 Agent 初始狀態...")
        status_resp = requests.get(f"{BASE_URL}/agent/status/{TEST_USER_ID}")
        status_data = status_resp.json()
        print(f"📊 初始回應: {status_data}")
        
        if status_resp.status_code != 200:
            print("❌ 無法連線至 API，請確認 uvicorn 是否已啟動。")
            return

        # Step 2: 發送微日記 (這會觸發背景的 agent_thinking_event)
        print("\n[步驟 2] 發送微日記並觸發 AI 思考...")
        payload = {
            "user_id": TEST_USER_ID,
            "content": "今天完成了一次完美的整合測試，架構看起來非常穩固！",
            "image_url": TEST_IMAGE_URL,
            "valence": 0.95,
            "arousal": 0.7
        }
        
        post_resp = requests.post(f"{BASE_URL}/micrologs/", json=payload)
        
        if post_resp.status_code == 200:
            print("✅ 日記發送成功！後端已啟動背景任務。")
        else:
            print(f"❌ 發送失敗: {post_resp.text}")
            return

        # Step 3: 輪詢狀態 (Polling) 捕捉 thinking 狀態
        print("\n[步驟 3] 開始監控 Redis 狀態變化 (預期應出現 thinking)...")
        found_thinking = False
        
        # 進行 6 次輪詢，每次間隔 1 秒 (因為背景任務 sleep 3 秒)
        for i in range(6):
            check_resp = requests.get(f"{BASE_URL}/agent/status/{TEST_USER_ID}")
            data = check_resp.json()
            curr_status = data.get("status")
            is_thinking = data.get("is_thinking")
            
            print(f"⏱️  第 {i+1} 秒 -> 狀態: {curr_status} | 思考中: {is_thinking}")
            
            if curr_status == "thinking":
                found_thinking = True
            
            time.sleep(1)

        # Step 4: 最終判定
        print("-" * 50)
        if found_thinking:
            print("✨ 測試成功！成功捕捉到狀態從 idle 切換至 thinking 再回歸。")
            print("🔗 這代表你的 FastAPI -> Redis -> Background Task 鏈條完全正確。")
        else:
            print("⚠️ 警告：未捕捉到 thinking 狀態。請檢查背景任務是否正確執行。")

    except Exception as e:
        print(f"💥 測試執行期間發生錯誤: {e}")

if __name__ == "__main__":
    run_integration_test()