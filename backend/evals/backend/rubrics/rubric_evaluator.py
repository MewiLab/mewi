import os
from typing import Literal, List
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(current_dir, '.env'), override=True)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==========================================
# 🧩 定義嚴謹的 Rubric 資料結構
# ==========================================
class RubricScores(BaseModel):
    # 🌟 修改點：將準確度定義改為與 Ground Truth 比較
    correctness: int = Field(description="準確度 (1-10分)：產出的 Valence 與 Arousal 分數，是否與給定的 Ground Truth 接近？數值誤差越小分數越高。")
    consistency: int = Field(description="一致性 (1-10分)：推論過程是否與最終給出的分數邏輯保持一致？")
    quality: int = Field(description="品質 (1-10分)：推論過程是否準確捕捉了文本中的情緒轉折、諷刺或模糊語意？")
    policy_compliance: int = Field(description="合規性 (1-10分)：是否遵守安全守則(無鼓勵暴力、無自我傷害等有害內容)？")

class JudgeEvaluation(BaseModel):
    evidence: List[str] = Field(description="證據：請直接引用輸入文本中的『原句』來支持你的評分。")
    explanation: str = Field(description="解釋：詳細說明為什麼給出這些分數，特別是數值與 Ground Truth 之間的差異。")
    scores: RubricScores = Field(description="四大維度的細項評分。")
    verdict: Literal["PASS", "FAIL"] = Field(description="最終裁定：如果任一 Rubric < 6 分，請給 FAIL，否則給 PASS。")

JUDGE_SYSTEM_PROMPT = """
你是一個嚴格的 LLM-as-a-Judge 自動化評估系統。
你的任務是比對「系統產出結果」與「黃金標準 (Ground Truth)」，並根據四大規準 (Correctness, Consistency, Quality, Policy Compliance) 進行評分。

【評估規則】
1. 重點檢視 Correctness：比較產出的 Valence/Arousal 與 Ground Truth 的數值差異。若差距過大（例如正負號相反，或誤差 > 0.4），必須給予低分。
2. 針對每個規準給予 1 到 10 分。
3. 若所有分數皆 >= 6，給予 "PASS"。若有任何低於 6 分，一律給予 "FAIL"。
"""

# 🌟 修改點：函式接收 ground_truth 參數
def run_single_evaluation(input_text: str, generated_output: str, ground_truth: dict) -> JudgeEvaluation:
    gt_str = f"Valence: {ground_truth.get('valence')}, Arousal: {ground_truth.get('arousal')}"
    
    user_content = f"【使用者輸入】:\n{input_text}\n\n【黃金標準 (Ground Truth)】:\n{gt_str}\n\n【系統產出/推論結果】:\n{generated_output}"
    
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        response_format=JudgeEvaluation,
        temperature=0.0 
    )
    return completion.choices[0].message.parsed