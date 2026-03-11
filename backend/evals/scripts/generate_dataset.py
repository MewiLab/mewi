import os
import json
import time
from openai import OpenAI

# 1. GITHUB TOKEN 只能使用50次請求
GITHUB_TOKEN = "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"
ENDPOINT = "https://models.inference.ai.azure.com"
MODEL_NAME = "gpt-4o" 

client = OpenAI(
    base_url=ENDPOINT,
    api_key=GITHUB_TOKEN,
)

def call_llm(prompt):
    """通用的 LLM 呼叫與 JSON 清理邏輯"""
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "你是一位資深 NLP 資料專家。請只輸出純 JSON Array，禁止解釋。"},
                {"role": "user", "content": prompt}
            ],
            model=MODEL_NAME,
            temperature=0.85
        )
        content = response.choices[0].message.content.strip()
        
        # 清理 Markdown 標籤
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:].strip()
            elif content.startswith("\n"):
                content = content.strip()
        
        return json.loads(content)
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        # 回傳 None 讓 main() 判斷是否為 API 限制 (如 429)
        return None

def fetch_batch_data(prompt_type, mode="long", count=10):
    """
    生成一般基礎資料 (General Base)
    定義真實存在的成大地點白名單 (White-list) TODO
    real_locations = [
        "勝利校區計中", "光復校區總圖", "育樂街", "東寧路", "成功湖", 
        "自強校區工學院實驗室", "光復校區操場", "勝後小吃部", "南門庭院", 
        "大學路星巴克", "光復校區學生第二活動中心", "自強校區電機系館"
    ]
    location_str = "、".join(real_locations)
    """
    if mode == "long":
        length_desc = "【硬性要求：長句型】字數必須嚴格介於 80 到 100 字中文之間。包含環境描寫與內心戲，嚴禁寫短句。"
        example_base = "範例：『今天下午在勝利校區的計中待了快三個小時，主要是在處理 C++ 作業的指標邏輯，雖然冷氣開得很強讓我手有點僵硬，但好險在離開前把所有測資都跑過了，走出大樓看到夕陽心情還算穩定。』"
        example_edge = "範例：『剛離開自強校區實驗室，感覺我的腦袋就像沒存檔的程式碼一樣空洞，看著成功湖的夕陽，突然覺得這種期中考前的焦慮就像無窮迴圈一樣跑不完，真的很諷刺。』"
    else:
        length_desc = "【硬性要求：短句型】字數必須嚴格介於 20 到 40 字中文之間。語氣簡短，像傳 Line。"
        example_base = "範例：『計中冷氣超冷，寫完 C++ 作業了，晚點去育樂街買飯。』"
        example_edge = "範例：『Bug 真貼心，陪我到凌晨四點，看來它比我女朋友還專情。』"

    base_context = (
        f"你是一位成大學生。{length_desc}\n"
        "內容須包含成大生活細節。數值規範：Valence [-1.0, 1.0], Arousal [0.0, 1.0]。請務必包含負值。"
    )

    prompts = {
        "general_base": f"{base_context}\n請生成 {count} 筆「直白事實」日記。標籤 Edge。\n{example_base}\n格式：JSON Array [{{id, text, lbs_context, ground_truth:{{valence, arousal}}, routing_label:'Edge'}}, ...]",
        "edge_cases": f"{base_context}\n請生成 {count} 筆「隱喻、反諷或深層情緒」日記。標籤 Cloud。\n{example_edge}\n格式：JSON Array [{{id, text, lbs_context, ground_truth, routing_label:'Cloud'}}, ...]"
    }

    return call_llm(prompts[prompt_type])

def main():
    # 2. 自動計算路徑：確保存入與 scripts 同級的 data/raw
    current_script_path = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.abspath(os.path.join(current_script_path, "..", "data", "raw"))
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 目標：長/短句各類別生 10 批，每批 20 筆 = 200 筆
    for mode in ["long", "short"]:
        for category in ["general_base", "edge_cases"]:
            print(f"🔥 開始生成任務：[{mode.upper()}] - {category}")
            final_list = []
            
            # 建立存檔路徑
            file_name = f"{category}_{mode}_gpt4o.json"
            save_path = os.path.join(output_dir, file_name)
            
            # 讀取現有進度，避免 429 中斷後需要重頭來過
            if os.path.exists(save_path):
                with open(save_path, "r", encoding="utf-8") as f:
                    final_list = json.load(f)
                print(f"📦 已載入既有資料: {len(final_list)} 筆")

            for i in range(10): 
                if len(final_list) >= 200:
                    print(f"✨ {file_name} 已滿 200 筆。")
                    break

                print(f"⏳ 正在獲取批次 {i+1}/10...")
                batch = fetch_batch_data(category, mode=mode, count=20)
                
                # 若 batch 為 None 代表觸發 API 限制或錯誤，直接跳出當前類別生成
                if batch is None:
                    print("🛑 偵測到 API 限制或網路錯誤，存檔並跳出。")
                    break
                
                final_list.extend(batch)
                
                # 每次獲取完立即寫入，確保資料安全
                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(final_list, f, ensure_ascii=False, indent=2)
                
                print(f"✅ 成功累積 {len(final_list)} 筆")
                time.sleep(5) # 建議設為 5 秒，對 GitHub Models 較友善
            
            print(f"🏁 {mode}-{category} 任務結束。\n")

if __name__ == "__main__":
    main()