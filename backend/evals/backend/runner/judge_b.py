import os
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(current_dir, '.env'), override=True)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 1. 定義強制輸出的資料格式
class AmbiguityResult(BaseModel):
    reasoning: str = Field(description="推論過程。判斷文本是否有字面與實際情緒不符、諷刺、或是資訊不足的狀況。")
    ambiguity_level: str = Field(description="只能是 'Low', 'Medium', 'High' 其中之一。")

# 2. 定義系統提示詞 (System Prompt)
AGENT_B_SYSTEM_PROMPT = """
你是一位語意學與語用學分析師，專門評估使用者「微日記」與「環境(LBS)」之間的「模糊度 (Ambiguity)」。

【評分標準 - Ambiguity Level】
- Low (低模糊度) : 字面意思直接、情緒單一且明確，沒有反串或隱喻。(例如："今天天氣很好，吃了好吃的漢堡，開心！")
- Medium (中模糊度) : 包含輕微的轉折、抒情式的隱喻，或需要結合一點環境上下文才能確切理解情緒。(例如："雨一直下，我的心也跟著發霉了。")
- High (高模糊度) : 包含強烈的正反情緒交雜、諷刺 (Sarcasm)、正話反說，或是文本情緒與所處的環境(LBS)產生極大矛盾。(例如："被老闆大罵一頓，真是太『棒』了，我都不知道該哭還是該笑。")

請先在 reasoning 欄位中進行推論，再給出 ambiguity_level。
"""

def run_agent_b(micro_log: str, context: str, debate_history: str = "") -> AmbiguityResult:
    user_content = f"【微日記】: {micro_log}\n【環境/視覺上下文】: {context}"
    
    if debate_history:
        user_content += f"\n\n【前一輪辯論紀錄與裁判長意見】:\n{debate_history}\n請參考上述意見重新評估。"

    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": AGENT_B_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        response_format=AmbiguityResult,
        temperature=0.2
    )
    return completion.choices[0].message.parsed

# --- 測試區塊 ---
if __name__ == "__main__":
    test_log = "本來以為會被老闆罵，結果竟然過關了，現在整個人有點脫力。"
    test_context = "辦公室，下午 5 點"
    print("正在呼叫 Agent B 進行模糊度解析...")
    result = run_agent_b(test_log, test_context)
    print(f"\n✅ 解析完成：\n推論: {result.reasoning}\n模糊度: {result.ambiguity_level}")