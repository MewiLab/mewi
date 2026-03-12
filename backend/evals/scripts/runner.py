import subprocess
import time

# --- 請填入你的 API Token ---
MY_API_KEY = "YOUR_API_KEY"

# 定義實驗矩陣
modes = ["long", "short"]
categories = ["edge", "cloud"]
# noises 0.1 代表正常數據，0.7 或 0.8 代表壓力測試數據
noises = [0.1, 0.8] 

def run_all():
    print("🚀 開始執行全自動生成任務...")
    start_time = time.time()

    for m in modes:
        for c in categories:
            for n in noises:
                # 組合名稱，方便你查看進度
                print(f"\n--- 正在生成組合: {m.upper()} | {c.upper()} | Noise: {n} ---")
                
                # 呼叫你的 generate_dataset.py
                cmd = [
                    "python", "generate_dataset.py",
                    "--api_key", MY_API_KEY,
                    "--mode", m,
                    "--category", c,
                    "--noise", str(n),
                    "--count", "20"  # 這裡直接設定為 20 筆
                ]
                
                # 執行指令
                try:
                    subprocess.run(cmd, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"❌ 執行失敗: {e}")
                
                # 緩衝 2 秒，避免 GitHub API 的 Rate Limit (頻率限制)
                time.sleep(2)

    end_time = time.time()
    duration = round((end_time - start_time) / 60, 2)
    print(f"\n✨ 所有任務已完成！總耗時: {duration} 分鐘")

if __name__ == "__main__":
    run_all()