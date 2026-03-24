# """
# EDD Eval Runner Interface
 
# Usage:
#     uv run python run_eval.py --eval_type backend
#     uv run python run_eval.py --eval_type backend --config pr_subset.yaml
# """

# import argparse
# import sys
# import logging

# # Why: print() disappears in production. logging lets you control
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s",
# )
# logger = logging.getLogger(__name__)


# # Why: a dict is easier to extend than if/elif chains
# # To add a new eval type, just add one line here
# EVAL_REGISTRY = {
#     "backend": "backend.run_backend_eval", 
# }

# def run_eval(eval_type: str, config: str | None=None) -> bool:
#     """
#     Dynamically import and run the eval moduler for the given type.
#     Returns True on success, False on failure.
#     """
#     module_path = EVAL_REGISTRY.get(eval_type)
    
#     if module_path is None:
#         logger.error(
#             "Unknown eval_type '%s'. Available: %s",
#             eval_type,
#             list(EVAL_REGISTRY.keys())
#         )
#         return False
    
#     # Why dynamic import: avoids importing every eval module at startup
#     # If you add 10 eval types later, only the requested one loads
#     try:
#         import importlib
#         module = importlib.import_module(module_path)
#     except ImportError as e:
#         logger.error("Could not import module '%s' : %s", module_path, e)
#         return False
    
    
#     # Every eval module must expose a `run(config)` function
#     if not hasattr(module, "run"):
#         logger.error("Module '%s' has no run() function.", module_path)
#         return False

#     try:
#         module.run(config=config)
#         return True
#     except Exception:
#         logger.exception("Eval '%s' failed with an error.", eval_type)
#         return False
    
    
# def main():
#     parser = argparse.ArgumentParser(description="EDD eval runner interface")
    
#     parser.add_argument(
#         "--eval_type", 
#         type=str, 
#         required=True,
#         choices=EVAL_REGISTRY.keys(),
#         help="Which eval suite to run.",
#     )

#     parser.add_argument(
#         "--config",
#         type=str,
#         default=None,
#         help="Optional config filename (e.g. pr_subset.yaml).",
#     )
        
#     args = parser.parse_args()
    
#     success = run_eval(args.eval_type, config=args.config)
    
#     # Why sys.exit: in CI (GitHub Actions), a non-zero exit code
#     if not success:
#         sys.exit(1)

# Why this guard: without it, `main()` runs on import too.
#!/usr/bin/env python3
"""CLI entry point for the E2E Agentic System eval runner.

Usage (from project root):
    python evals/run_eval.py --input evals/scripts/data_cloud_short_zh.json --output evals/scripts/results.json

Exit codes:
    0 — suite passed all thresholds
    1 — suite failed, or a hard error occurred

Why a separate entry point?
  GitHub Actions reads the exit code to set the PR status check.
  Keeping it thin lets us test the runner logic without spawning a subprocess.
"""

import argparse
import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. 將 evals/ 目錄加入 sys.path，確保 backend.runner... 的 import 絕對能解析
evals_dir = Path(__file__).parent
sys.path.insert(0, str(evals_dir))

# 載入環境變數 (.env)
load_dotenv(dotenv_path=evals_dir / '.env', override=True)

# 引入我們自訂的評估模組
from backend.runner.meta_judge import get_panel_consensus
from backend.rubrics.rubric_evaluator import run_agentic_evaluation

def run_eval_pipeline(input_file: str, output_file: str, pass_threshold: float = 0.8) -> dict:
    """執行端到端評估，並回傳 CI 需要的 Summary 數據。"""
    
    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"找不到測試資料檔: {input_path}")

    with open(input_path, 'r', encoding='utf-8') as f:
        test_cases = json.load(f)

    results = []
    total_cases = len(test_cases)
    
    # 統計用變數
    passed_count = 0
    total_score = 0
    schema_errors = 0

    for idx, case in enumerate(test_cases):
        log_id = case.get("id", f"log_{idx}")
        text = case.get("text", "")
        raw_lbs = case.get("lbs_context")
        context = raw_lbs if raw_lbs is not None else "無 LBS 資訊"
        ground_truth = case.get("ground_truth", {"valence": 0.0, "arousal": 0.0})
        
        print(f"🔄 [進度 {idx+1}/{total_cases}] 評估 ID: {log_id} ...", end=" ", flush=True)

        try:
            # 步驟 A: 多代理人陪審團產生結果
            consensus = get_panel_consensus(text, context)
            generated_output = f"Valence: {consensus.final_valence}, Arousal: {consensus.final_arousal}, Ambiguity: {consensus.final_ambiguity}\nReasoning: {consensus.final_reasoning}"
            
            # 步驟 B: Rubric Evaluator 進行嚴格審核
            eval_checks = {
                "must_be_valid_json": True,
                "must_be_concise": True,
                "ground_truth_for_scoring": ground_truth 
            }
            user_input_context = f"Micro-log: {text} | LBS: {context}"
            
            rubric_report = run_agentic_evaluation(
                user_input=user_input_context, 
                candidate_text=generated_output, 
                checks=eval_checks
            )
            
            # 收集評估數據
            is_pass = rubric_report.get("pass", False)
            score = rubric_report.get("score", 0)
            
            if is_pass:
                passed_count += 1
            total_score += score
            
            # 如果法官回傳的格式有缺漏，計入 schema error
            if "pass" not in rubric_report or "score" not in rubric_report:
                schema_errors += 1

            print(f"{'✅ PASS' if is_pass else '❌ FAIL'} (Score: {score}/5)")

            # 儲存紀錄
            results.append({
                "id": log_id,
                "input_text": text,
                "ground_truth": ground_truth,
                "panel_consensus": consensus.model_dump(),
                "evaluation_report": rubric_report
            })

        except Exception as e:
            print(f"⚠️ 發生錯誤: {e}")
            schema_errors += 1

    # 寫入詳細報告
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    # 計算統計摘要 (Summary)
    pass_rate = passed_count / total_cases if total_cases > 0 else 0.0
    avg_score = total_score / total_cases if total_cases > 0 else 0.0
    schema_error_rate = schema_errors / total_cases if total_cases > 0 else 0.0
    
    # 判斷整個測試套件是否達標 (例如：過關率 >= 80%)
    suite_pass = pass_rate >= pass_threshold

    return {
        "suite_pass": suite_pass,
        "pass_rate": pass_rate,
        "avg_score": avg_score,
        "schema_error_rate": schema_error_rate,
        "total_cases": total_cases
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Run an eval suite.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the input JSON file (e.g., evals/scripts/data_cloud_short_zh.json)",
    )
    parser.add_argument(
        "--output",
        default="evals/scripts/eval_results.json",
        help="Path to save the detailed evaluation report.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Pass rate threshold to consider the suite successful (default: 0.8 -> 80%).",
    )
    args = parser.parse_args()

    print(f"🚀 Starting Eval Suite")
    print(f"Input: {args.input}\n")

    try:
        summary = run_eval_pipeline(args.input, args.output, args.threshold)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # Pretty-print the summary so it appears cleanly in the CI log
    print("\n" + "="*40)
    print("📊 Evaluation Summary:")
    print(json.dumps(summary, indent=2))
    print("="*40)

    status = "PASSED" if summary["suite_pass"] else "FAILED"
    print(
        f"\nSuite {status} — "
        f"pass_rate={summary['pass_rate']:.1%}  "
        f"avg_score={summary['avg_score']:.2f}  "
        f"schema_errors={summary['schema_error_rate']:.1%}"
    )

    # Github Actions 依靠這裡的 Exit code 決定 PR 是否能合併
    if not summary["suite_pass"]:
        sys.exit(1)

if __name__ == "__main__":
    main()