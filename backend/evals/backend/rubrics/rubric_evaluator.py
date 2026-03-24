import os
import json
from openai import OpenAI
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(current_dir, '.env'), override=True)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==========================================
# 📝 定義系統提示詞 (依據您提供的規格)
# ==========================================
EVALUATOR_SYSTEM_PROMPT = """
You are a strict evaluator for an agentic system.

You will be given:
- input: the user request / scenario
- candidate: the system's output
- checks: optional constraints

Your job:
1) Evaluate correctness and compliance with checks.
2) Produce a STRICT JSON object only (no extra text).

Scoring (0-5):
- 5: fully correct, follows all constraints
- 4: minor issues but still acceptable
- 3: noticeable issues; partially meets intent/constraints
- 2: mostly incorrect or violates constraints
- 1: completely wrong
- 0: unsafe, nonsensical, or totally non-compliant

Rules:
- If checks.must_be_valid_json is true: candidate.text MUST parse as JSON.
- If checks.required_keys exists: JSON must contain those keys.
- If checks.max_sentences exists: candidate must not exceed that number of sentences.
- If checks.must_be_concise is true: penalize fluff.

Return JSON schema:
{
  "pass": boolean,
  "score": number,            // integer 0..5
  "reasons": string[],        // short bullet-like reasons
  "parsed_json": object|null  // if candidate is valid JSON, else null
}
"""

# ==========================================
# 🚀 核心評估函式
# ==========================================
def run_agentic_evaluation(user_input: str, candidate_text: str, checks: dict = None) -> dict:
    """
    執行 Agentic System 評估。
    回傳值將是一個 Python Dictionary，結構符合上述 Return JSON schema。
    """
    if checks is None:
        checks = {}

    # 將輸入資料打包成 JSON 格式餵給 LLM，這樣最符合 "You will be given: input, candidate, checks" 的語境
    user_payload = {
        "input": user_input,
        "candidate": {
            "text": candidate_text
        },
        "checks": checks
    }

    completion = client.chat.completions.create(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)}
        ],
        response_format={"type": "json_object"}, # 啟動強制 JSON 模式
        temperature=0.0 # 評估器需要絕對客觀，溫度設為 0
    )
    
    # 解析回傳的 JSON 字串成 Python Dictionary
    result_str = completion.choices[0].message.content
    return json.loads(result_str)

# ==========================================
# 🧪 測試區塊 (模擬帶有 Checks 的測試)
# ==========================================
if __name__ == "__main__":
    test_input = "請分析使用者的微日記情緒，並回傳包含 valence 和 arousal 的 JSON。"
    
    # 模擬一個「不合格」的 Agent 輸出（有廢話，且格式不正確）
    bad_candidate = "好的！這是我為您分析的結果：\n{\"valence\": 0.8, \"arousal_level\": 0.5}\n希望這對您有幫助！"
    
    # 設定嚴格的評估條件
    strict_checks = {
        "must_be_valid_json": True,
        "required_keys": ["valence", "arousal"],
        "must_be_concise": True
    }
    
    print("正在執行嚴格 Agentic 評估...")
    report = run_agentic_evaluation(test_input, bad_candidate, strict_checks)
    
    print("\n🎯 評估結果：")
    print(json.dumps(report, ensure_ascii=False, indent=2))