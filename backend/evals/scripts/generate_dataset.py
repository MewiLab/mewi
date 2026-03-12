import os
import json
import time
import argparse
import random
import re  # 新增：用於清洗字串
from openai import OpenAI

def parse_args():
    parser = argparse.ArgumentParser(description="MEW Dataset Generator v2.3 - High Noise Edition")
    parser.add_argument("--api_key", type=str, required=True, help="GitHub Models API Key")
    parser.add_argument("--dept", type=str, default="資工系", help="學生系所")
    parser.add_argument("--lang", type=str, choices=["zh", "en"], default="zh", help="生成語言")
    parser.add_argument("--mode", type=str, choices=["long", "short"], default="long", help="長篇(80-100)或短篇(20-40)")
    parser.add_argument("--category", type=str, choices=["edge", "cloud"], default="edge", help="路由分類")
    parser.add_argument("--count", type=int, default=10, help="數量")
    parser.add_argument("--noise", type=float, default=0.2, help="雜訊機率 (0.0~1.0)")
    return parser.parse_args()

REAL_LOCATIONS = ["光復聖誕樹", "成功湖", "小西門", "總圖", "育樂街"]

def generate_prompt(args):
    loc_str = "、".join(REAL_LOCATIONS)
    lang_str = "繁體中文" if args.lang == "zh" else "English"
    
    if args.mode == "long":
        length_req = "80 到 100 字，包含大量環境描寫與心理戲"
        example = "範例：『今天下午在總圖待了快四個小時，指標邏輯還是卡住，窗外的夕陽照在成功湖上很美，但我現在只想把這段 code 燒掉。』"
    else:
        length_req = "20 到 40 字，語氣簡短像傳 Line"
        example = "範例：『育樂街人超多，排隊排到心累。』"

    noise_instr = ""
    if args.noise > 0:
        noise_instr = (
            f"【極限噪聲注入 (機率 {args.noise})】：\n"
            "1. 隨機打錯字（如：邏輯->裸機、成功湖->成公湖）。\n"
            "2. 隨機漏掉標點或加入無意義符號（如：#、$）。\n"
            "3. 語法凌亂，像是在跑步或單手打字的感覺。\n"
            "**警告：噪聲僅限於 text 內容，嚴禁破壞 JSON 的 Key 或結構符號（如 [ ] { } : , \"）。**\n"
        )

    prompt = (
        f"你是一位成大{args.dept}學生。請用{lang_str}生成 {args.count} 則微日記。\n"
        f"【硬性限制】：\n"
        f"1. 每則字數：嚴格介於 {length_req}。\n"
        f"2. 地點約束：從 [{loc_str}] 中『隨機』選取，禁止按順序排列。部分日記可不提地點。\n"
        f"3. 情感數值：V: [-1, 1], A: [0, 1]。\n"
        f"4. 語意風格：{'直白事實' if args.category == 'edge' else '反諷隱喻或深層情緒'}。\n"
        f"{noise_instr}"
        f"\n{example}\n"
        f"【格式】：純 JSON Array，禁止任何解釋文字。格式：\n"
        f"[{{id, text, lbs_context, ground_truth:{{valence, arousal}}, routing_label:'{args.category.capitalize()}'}}]"
    )
    return prompt

def main():
    args = parse_args()
    client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=args.api_key)

    print(f"⏳ 正在生成: {args.category} | {args.mode} | Noise: {args.noise}")
    
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "你是一位專門製造『不完美數據』的 NLP 專家。你必須確保輸出為合法的 JSON 格式。"},
                {"role": "user", "content": generate_prompt(args)}
            ],
            model="gpt-4o",
            temperature=0.85 # 稍微調低一點，增加結構穩定性
        )
        
        raw_content = response.choices[0].message.content.strip()
        
        # --- 強力清洗 JSON 邏輯 ---
        # 使用正則表達式抓取 [ 到 ] 之間的內容
        match = re.search(r'\[.*\]', raw_content, re.DOTALL)
        if match:
            clean_content = match.group(0)
        else:
            clean_content = raw_content

        new_data = json.loads(clean_content)
        filename = f"data_{args.category}_{args.mode}_{args.lang}.json"
        
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            start_id = existing_data[-1]['id'] + 1 if existing_data else 1
            for i, item in enumerate(new_data):
                item['id'] = start_id + i
            combined_data = existing_data + new_data
        else:
            combined_data = new_data

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(combined_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 完成！目前檔案規模: {len(combined_data)} 筆")

    except Exception as e:
        print(f"❌ 錯誤: {e}")
        # 發生錯誤時印出部分原始內容，方便 Debug
        print(f"原始回傳預覽: {raw_content[:100]}...")

if __name__ == "__main__":
    main()