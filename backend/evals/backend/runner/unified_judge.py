import os
from typing import Literal
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
# 確保指向正確的 .env 位置
load_dotenv(dotenv_path=os.path.join(current_dir, '../../.env'), override=True)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==========================================
# 🧩 1. 定義單一輸出的資料格式 (Pydantic Schema)
# ==========================================
class EmotionResult(BaseModel):
    ambiguity_level: Literal["Low", "Medium", "High"] = Field(
        description="模糊度等級。Low: 字面意思等於真實情緒。High: 帶有強烈諷刺、反串或正負情緒夾雜。"
    )
    reasoning: str = Field(
        description="推論過程。請先分析文本的模糊度與潛台詞，結合 LBS 上下文，最後再解釋給出的 VA 分數。"
    )
    valence: float = Field(
        description="情緒效價 (Valence)。範圍 -1.0 (極度負面) 到 1.0 (極度正面)。0.0為中性。"
    )
    arousal: float = Field(
        description="喚起度 (Arousal)。範圍 0.0 (極度平靜/疲倦) 到 1.0 (極度激動/警覺)。"
    )

# ==========================================
# 📝 2. 統整版系統提示詞 (System Prompt)
# ==========================================
UNIFIED_JUDGE_PROMPT = """
你是一位兼具「語意學家」與「臨床心理學家」專業的 AI 代理人。
你的任務是精準解析使用者的「微日記」與「地理上下文 (LBS)」，並萃取出真實的情緒狀態。

【分析步驟】
1. 先判斷文本的 Ambiguity (模糊度)：使用者是否在使用反諷 (Sarcasm)？是否表面說「太棒了」實則「極度崩潰」？
2. 根據真實的潛台詞，給出 Valence (情緒效價) 與 Arousal (喚起度)。

【Valence 評分標準 (-1.0 ~ 1.0)】
- 1.0 : 極度狂喜、強烈的正向情緒。
- 0.5 : 開心、放鬆、日常的小確幸。
- 0.0 : 完全無情緒起伏的中性敘述。
- -0.5: 焦慮、挫折、日常壓力。
- -1.0: 極度絕望、深層悲痛、狂怒或崩潰。

【Arousal 評分標準 (0.0 ~ 1.0)】
- 1.0 : 極度激動、暴怒、狂喜、心跳加速。
- 0.5 : 正常活動狀態、輕微焦慮或興奮。
- 0.0 : 極度放鬆、想睡、疲倦、無力。

請務必識破任何反諷，並給出反映「使用者真實內心狀態」的數值。
"""

# ==========================================
# 🚀 3. 核心執行函式
# ==========================================
def run_unified_judge(micro_log: str, context: str) -> EmotionResult:
    user_content = f"【微日記】: {micro_log}\n【環境/視覺上下文】: {context}"
    
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": UNIFIED_JUDGE_PROMPT},
            {"role": "user", "content": user_content}
        ],
        response_format=EmotionResult,
        temperature=0.1 # 保持低溫度以追求穩定的解析
    )
    
    return completion.choices[0].message.parsed

# ==========================================
# 🧪 4. 簡單測試區塊
# ==========================================
if __name__ == "__main__":
    # 測試一個帶有反諷的例子
    test_text = "今天搞 React Native 搞到崩潰，環境一直踩坑，真是太『神』了，什麼 code 都沒寫到。"
    test_context = "咖啡廳，下午 5 點"
    
    print("正在執行單一核心法官解析...")
    result = run_unified_judge(test_text, test_context)
    
    print("\n✅ 解析完成：")
    print(f"模糊度 (Ambiguity): {result.ambiguity_level}")
    print(f"推論 (Reasoning)  : {result.reasoning}")
    print(f"Valence (效價)    : {result.valence}")
    print(f"Arousal (喚起度)  : {result.arousal}")