import subprocess
import time
import argparse

def parse_runner_args():
    parser = argparse.ArgumentParser(description="MEW Automated Generation Pipeline Runner")
    parser.add_argument("--api_key", type=str, required=True, help="GitHub Models API Key")
    parser.add_argument("--count", type=int, default=10, help="每個組合生成的數量")
    return parser.parse_args()

# 實驗矩陣
modes = ["long", "short"]
categories = ["edge", "cloud"]
noises = [0.1, 0.5] 
langs = ["zh"] 

def run_all():
    args = parse_runner_args()
    
    print("🚀 啟動全自動生成管線 (精簡額度模式)...")
    start_time = time.time()
    request_count = 0

    for l in langs:
        for m in modes:
            for c in categories:
                for n in noises:
                    request_count += 1
                    print(f"\n⚡ [{request_count}] 執行組合: {m.upper()} | {c.upper()} | Noise: {n} | Lang: {l}")
                    
                    # 這裡會將 args.api_key 傳遞給下層的 generate_dataset.py
                    cmd = [
                        "python", "generate_dataset.py",
                        "--api_key", args.api_key,
                        "--mode", m,
                        "--category", c,
                        "--lang", l,
                        "--noise", str(n),
                        "--count", str(args.count)
                    ]
                    
                    try:
                        subprocess.run(cmd, check=True)
                    except subprocess.CalledProcessError as e:
                        print(f"⚠️ 組合 {m}-{c} 失敗，原因: {e}")
                    
                    # 延遲確保 API 穩定
                    time.sleep(4)

    duration = round((time.time() - start_time) / 60, 2)
    print(f"\n✨ 任務結束！總共發出 {request_count} 次請求。")
    print(f"總耗時: {duration} 分鐘。")
    print("📂 資料已自動累加至對應的 JSON 檔案中。")

if __name__ == "__main__":
    run_all()