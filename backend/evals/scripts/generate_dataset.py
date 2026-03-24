import os
import json
import time
import argparse
import random
import re
from openai import OpenAI

def parse_args():
    parser = argparse.ArgumentParser(description="MEW Dataset Generator v2.8")
    parser.add_argument("--api_key", type=str, required=True, help="GitHub Models API Key")
    parser.add_argument("--dept", type=str, default="資工系", help="學生系所")
    parser.add_argument("--lang", type=str, choices=["zh", "en"], default="zh", help="生成語言")
    parser.add_argument("--mode", type=str, choices=["long", "short"], default="long", help="長篇(80-120)或短篇(20-40)")
    parser.add_argument("--category", type=str, choices=["edge", "cloud"], default="edge", help="路由分類")
    parser.add_argument("--count", type=int, default=10, help="數量")
    parser.add_argument("--noise", type=float, default=0.2, help="雜訊機率 (0.0~1.0)")
    return parser.parse_args()

REAL_LOCATIONS = ["光復聖誕樹", "成功湖", "小西門", "總圖", "育樂街"]

def generate_prompt(args):
    loc_str = "、".join(REAL_LOCATIONS)
    lang_str = "繁體中文" if args.lang == "zh" else "English"
    
    # --- 長度補丁：針對 Long 模式喊價喊高，強迫 AI 撐開字數 ---
    if args.mode == "long":
        # 標竿設為 100-150，這樣 AI 才會穩定產出 100 字左右的內容
        len_desc = "100 到 150 字" if args.lang == "zh" else "100 to 150 words"
        length_patch = (
            "【長度與細節強化補丁】：\n"
            "1. 禁止只寫大意，必須增加場景細節描述（如：冷氣聲、夕陽光影、周遭人潮聲）。\n"
            "2. 必須包含具體事件過程（如：代碼哪裡報錯、排隊時看到的細節）。\n"
            "3. 嚴格禁止低於 100 字（單字），請盡量擴充心理獨白。"
        )
    else:
        len_desc = "20 到 45 字" if args.lang == "zh" else "20 to 45 words"
        length_patch = "語氣簡短精煉，像發 Threads 或 Line。"

    if args.lang == "zh":
        # 中文範例 (字數計)
        if args.mode == "long":
            examples = (
                "範例 A (80字-含地點)：『今天下午在總圖待了很久，指標邏輯還是卡住，C 語言的記憶體錯誤搞得我頭好痛。看著窗外成功湖的夕陽很美，跟我的 Debug 慘況形成對比。雖然風景治癒，但我現在只想把這段 code 燒掉。』\n"
                "範例 B (100字-無地點)：『這幾天壓力真的很大，總覺得時間不夠用，每天都在跟進度賽跑，卻不知道自己到底在忙什麼。心情像台南的天氣一樣悶熱，卻又找不到出口宣洩，看著手機通訊錄卻不知道能撥給誰，這種孤獨感在深夜特別鮮明。好累，真的好想先睡個三天三夜。』\n"
                "範例 C (120字-含地點)：『育樂街新開的滷味排隊排到街口，等了半小時才輪到我。提著熱騰騰的滷味走回宿舍，看著小西門的城牆在夜色中顯得特別厚重，突然覺得這種平凡的飽足感就是一種幸福。雖然明天還有八點的演算法課，但看著流浪貓在城門下玩耍，心情好多了。希望明天作業能順利寫完。』"
            )
        else:
            examples = (
                "範例 A (20字-含地點)：『育樂街人超多，肚子快餓扁了，排隊排到心累。』\n"
                "範例 B (30字-無地點)：『今天沒什麼動力，看著螢幕發呆了很久，腦袋完全空空的。』\n"
                "範例 C (40字-含地點)：『坐在小西門旁看著老牆，突然覺得歷史好厚重，而我的考試壓力也一樣厚重。』"
            )
    else:
        # 英文範例 (單字計 Words)
        if args.mode == "long":
            examples = (
                "Example A (80 words - with Location): 'Spent four hours at the Main Library today. Still stuck on pointer logic; C memory errors are giving me a massive headache. Looking out the window, the golden sunset reflects on Cheng-Kung Lake. It is peaceful, but honestly, I just want to burn this code right now. The contrast between the beauty outside and the chaos on my screen is almost poetic in a tragic way.'\n"
                "Example B (100 words - No Location): 'The pressure has been immense lately. I feel like I am constantly racing against deadlines, yet I have no idea what I am actually achieving. My mind feels as humid and heavy as the weather in Tainan, with no outlet for all this pent-up frustration. Looking through my contacts, I realized there is no one I really want to call. This sense of isolation is particularly sharp in the middle of the night. I am just exhausted and need a long break from everything.'\n"
                "Example C (120 words - with Location): 'The new braised food stall on Yule Street had a line stretching all the way to the corner. I waited for half an hour before it was finally my turn. Walking back to the dorm with the steaming bag of food, I looked at the Small West Gate walls. They looked so heavy and solid in the night. It made me realize that this simple sense of fullness is a kind of happiness. Even though I have an 8 AM Algorithms class tomorrow, watching the stray cats play under the gate made me feel much better.' "
            )
        else:
            examples = (
                "Example A (20 words - with Location): 'Yule Street is packed. I am starving and the queue is soul-crushing.'\n"
                "Example B (30 words - No Location): 'Zero motivation today. Staring at the screen for hours with a completely blank mind. Just feeling empty.'\n"
                "Example C (40 words - with Location): 'Sitting by Small West Gate, the ancient walls feel heavy and ancient, just like the immense pressure of my upcoming final exams.'"
            )

    noise_instr = ""
    if args.noise > 0:
        noise_instr = (
            f"【極限噪聲注入 (機率 {args.noise})】：\n"
            "1. 隨機打錯字（如：邏輯->裸機）、漏標點或加入無意義符號（#、$）。\n"
            "2. 語法凌亂，模擬跑步或單手輸入。\n"
            "**警告：嚴禁在 text 內容中換行。噪聲僅限 text 內容，嚴禁破畫 JSON 結構。**\n"
        )

    prompt = (
        f"扮演成大{args.dept}學生，用{lang_str}生成 {args.count} 則微日記。\n"
        f"【硬性約束】：\n"
        f"1. **字數分佈**：嚴格介於 {len_desc}。請混合使用範例中的 A、B、C 三種長度級距。\n"
        f"2. **內容要求**：{length_patch}\n"
        f"3. **場景隨機**：約 40% 的日記 lbs_context 填 null（無地點），其餘從 [{loc_str}] 隨機選取。\n"
        f"4. **風格**：{'直白事實描述' if args.category == 'edge' else '反諷、隱喻或情緒抒發'}。V: [-1, 1], A: [0, 1]。\n"
        f"{noise_instr}\n"
        f"【參考範例集】：\n"
        f"{examples}\n\n"
        f"格式：純 JSON Array [{{id, text, lbs_context, ground_truth:{{valence, arousal}}, routing_label:'{args.category.capitalize()}'}}]"
    )
    return prompt

def main():
    args = parse_args()
    client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=args.api_key)

    print(f"⏳ 正在生成: {args.category} | {args.mode} | Noise: {args.noise} | Lang: {args.lang}")
    
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "你是一位專門製造不完美數據的 NLP 專家。你必須確保輸出為合法 JSON，且內容禁止換行。"},
                {"role": "user", "content": generate_prompt(args)}
            ],
            model="gpt-4o",
            temperature=0.95,
            max_tokens=4000
        )
        
        raw_content = response.choices[0].message.content.strip()
        
        # --- 超級清洗層 ---
        clean_content = re.sub(r'```json|```', '', raw_content).strip()
        clean_content = clean_content.replace('\n', ' ')
        match = re.search(r'\[.*\]', clean_content, re.DOTALL)
        if not match: raise ValueError("回傳內容不符合 JSON Array 格式")
        clean_content = match.group(0)

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
        with open("error_log.txt", "w", encoding="utf-8") as ef:
            ef.write(raw_content)
        print("💡 已將原始回傳存入 error_log.txt")

if __name__ == "__main__":
    main()