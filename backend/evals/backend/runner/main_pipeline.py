import os
import json
from dotenv import load_dotenv

from meta_judge import get_panel_consensus
from rubric_evaluator import run_single_evaluation

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(current_dir, '.env'), override=True)

def process_e2e_pipeline(input_filepath: str, output_filepath: str):
    print(f"📥 正在讀取測試資料: {input_filepath}")
    with open(input_filepath, 'r', encoding='utf-8') as f:
        test_cases = json.load(f)

    results = []
    total = len(test_cases)

    for idx, case in enumerate(test_cases):
        # 🌟 修改點 1：對應新的 JSON 欄位
        log_id = case.get("id", f"log_{idx}")
        text = case.get("text", "")
        
        # 🌟 修改點 2：處理 lbs_context 可能為 null (None) 的狀況
        raw_lbs = case.get("lbs_context")
        context = raw_lbs if raw_lbs is not None else "無 LBS 資訊"
        
        # 取得新欄位
        ground_truth = case.get("ground_truth", {"valence": 0.0, "arousal": 0.0})
        routing_label = case.get("routing_label", "Unknown")

        print(f"\n⚙️ [進度 {idx+1}/{total}] 處理 ID: {log_id} ({routing_label})")
        
        # --- 步驟 1: 呼叫 Meta-Judge 產生共識推論 ---
        print("  └ 1️⃣ 陪審團 (Agent A+B) 正在解析與辯論...")
        consensus = get_panel_consensus(text, context)
        
        generated_output = f"Valence: {consensus.final_valence}, Arousal: {consensus.final_arousal}, Ambiguity: {consensus.final_ambiguity}\n推論: {consensus.final_reasoning}"
        
        # --- 步驟 2: 呼叫 Rubric Evaluator (傳入 Ground Truth) ---
        print("  └ 2️⃣ 最終法官 (Rubric Evaluator) 正在進行審核...")
        rubric_report = run_single_evaluation(text, generated_output, ground_truth)
        
        print(f"  └ 🎯 審核結果: {rubric_report.verdict} (正確性: {rubric_report.scores.correctness} 分)")

        # --- 步驟 3: 儲存完整結果 ---
        results.append({
            "id": log_id,
            "routing_label": routing_label,
            "input_text": text,
            "lbs_context": context,
            "ground_truth": ground_truth,
            "panel_consensus": consensus.model_dump(),
            "rubric_evaluation": rubric_report.model_dump()
        })

    print(f"\n💾 處理完成！寫入至: {output_filepath}")
    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    print("✅ 寫入成功！")

if __name__ == "__main__":
    # 您可以把組員給的檔案名稱寫在這裡，例如 "data_cloud_short_zh.json"
    input_file = os.path.join(current_dir, "data_cloud_short_zh.json")
    output_file = os.path.join(current_dir, "evaluated_cloud_short.json")
    
    if os.path.exists(input_file):
        process_e2e_pipeline(input_file, output_file)
    else:
        print(f"❌ 找不到檔案 {input_file}，請確認檔案是否有放在資料夾中！")