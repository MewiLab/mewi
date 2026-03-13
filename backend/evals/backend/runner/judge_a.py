import os
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

# ==========================================
# 🔧 1. 環境變數與金鑰載入 (絕對路徑防呆版)
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')

# 加入 override=True，強制覆蓋掉系統可能殘留的舊環境變數
load_dotenv(dotenv_path=env_path, override=True)

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(f"無法讀取 API Key，請檢查 {env_path} 檔案是否存在且格式正確！")

client = OpenAI(api_key=api_key)

# ==========================================
# 🧩 2. 定義強制輸出的資料格式 (Pydantic Schema)
# ==========================================
class EmotionResult(BaseModel):
    reasoning: str = Field(description="推論過程。請先分析文本中的情緒關鍵字、LBS環境的影響，再給出最終分數的解釋。")
    valence: float = Field(description="情緒效價 (Valence)。範圍 -1.0 (極度負面) 到 1.0 (極度正面)。0.0為中性。")
    arousal: float = Field(description="喚起度 (Arousal)。範圍 0.0 (極度平靜/疲倦) 到 1.0 (極度激動/警覺)。")

# ==========================================
# 📝 3. 定義系統提示詞 (System Prompt)
# ==========================================
AGENT_A_SYSTEM_PROMPT = """
你是一位臨床心理學家，專門分析使用者的「微日記」與「環境上下文(LBS)」，並將其對應到 Russell 的情緒環狀模型 (Circumplex Model of Affect)。

【評分標準 - Valence (情緒效價 -1.0 ~ 1.0)】
- 1.0 : 極度狂喜、生命中的重大正面事件、強烈的愛與感恩。
- 0.5 : 開心、放鬆、日常的微小確幸 (例如：吃了一頓好吃的晚餐)。
- 0.0 : 完全無情緒起伏的客觀敘述 (例如：我今天搭捷運上班)。
- -0.5: 挫折、難過、焦慮、日常的壓力 (例如：被主管唸了一頓)。
- -1.0: 極度絕望、深層的悲痛或憤怒。

【評分標準 - Arousal (喚起度 0.0 ~ 1.0)】
- 1.0 : 極度激動、驚恐、暴怒、狂喜 (心跳加速、需要立即行動)。
- 0.5 : 保持警覺、正常活動狀態、輕微的興奮或焦慮。
- 0.0 : 極度放鬆、想睡、疲倦、無力。

請務必先在 reasoning 欄位中進行思考，再給出 valence 和 arousal 分數。
"""

# ==========================================
# 🚀 4. 核心評估函式
# ==========================================
def run_agent_a(micro_log: str, context: str, debate_history: str = "") -> EmotionResult:
    # 組合使用者的輸入
    user_content = f"【微日記】: {micro_log}\n【環境/視覺上下文】: {context}"
    
    # 如果有辯論歷史（來自裁判長退回重審），則附加在 Prompt 後方
    if debate_history:
        user_content += f"\n\n【前一輪辯論紀錄與裁判長意見】:\n{debate_history}\n請參考上述意見重新評估。"

    # 呼叫 OpenAI API，並強制轉換為 EmotionResult 格式
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06", # 支援 Structured Outputs 的模型
        messages=[
            {"role": "system", "content": AGENT_A_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        response_format=EmotionResult, 
        temperature=0.2 # 專家需要客觀穩定，溫度調低
    )

    return completion.choices[0].message.parsed

# ==========================================
# 🧪 5. 測試執行區塊
# ==========================================
if __name__ == "__main__":
    # 模擬一筆測試資料
    test_log = "本來以為會被老闆罵，結果竟然過關了，現在整個人有點脫力。"
    test_context = "辦公室，下午 5 點"
    
    print("正在呼叫 Agent A (心理學專家) 進行情緒解析...")
    result = run_agent_a(test_log, test_context)
    
    print("\n✅ 解析完成：")
    print(f"推論過程: {result.reasoning}")
    print(f"Valence (效價): {result.valence}")
    print(f"Arousal (喚起度): {result.arousal}")