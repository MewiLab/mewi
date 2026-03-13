import os
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

# 👉 這裡對應您統一的新檔名
from judge_a import run_agent_a
from judge_b import run_agent_b

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(current_dir, '.env'), override=True)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class ConsensusResult(BaseModel):
    has_conflict: bool = Field(description="Agent A 與 B 的評估是否產生邏輯矛盾？")
    debate_topic: str = Field(description="若有矛盾，寫下質疑點退回重審。")
    final_valence: float = Field(description="最終裁定的情緒效價 (-1.0 ~ 1.0)")
    final_arousal: float = Field(description="最終裁定的喚起度 (0.0 ~ 1.0)")
    final_ambiguity: str = Field(description="最終裁定的模糊度等級 (Low, Medium, High)")
    final_reasoning: str = Field(description="裁判長的綜合結論")

META_JUDGE_PROMPT = """
你是一個「AI 評估陪審團」的裁判長。
任務是審視「Agent A (心理專家)」與「Agent B (語意專家)」的評分。
1. 若 A 給出正向分數 (Valence > 0.6)，但 B 指出文本是「強烈諷刺 (High Ambiguity)」，這就是嚴重衝突！
2. 發現衝突請設 has_conflict = true 並發起 debate_topic 質疑點。
3. 若無衝突，請直接給出綜合 final 數值與結論。
"""

def run_meta_judge_single(micro_log: str, context: str, res_a, res_b) -> ConsensusResult:
    user_content = f"【微日記】: {micro_log}\n【上下文】: {context}\n【A報告】: Valence={res_a.valence}, 推論={res_a.reasoning}\n【B報告】: Ambiguity={res_b.ambiguity_level}, 推論={res_b.reasoning}"
    
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[{"role": "system", "content": META_JUDGE_PROMPT}, {"role": "user", "content": user_content}],
        response_format=ConsensusResult,
        temperature=0.1
    )
    return completion.choices[0].message.parsed

def get_panel_consensus(micro_log: str, context: str, max_rounds: int = 2) -> ConsensusResult:
    """執行多代理人辯論，取得最終共識結果"""
    debate_history = ""
    for round_num in range(max_rounds):
        res_a = run_agent_a(micro_log, context, debate_history)
        res_b = run_agent_b(micro_log, context, debate_history)
        consensus = run_meta_judge_single(micro_log, context, res_a, res_b)
        
        if not consensus.has_conflict:
            return consensus
        debate_history += f"【第{round_num+1}輪質疑】: {consensus.debate_topic}\n"
    return consensus