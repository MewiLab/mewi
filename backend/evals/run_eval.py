#!/usr/bin/env python3
"""CLI entry point for the eval runner.

Usage (from backend/):
    uv run python evals/run_eval.py --config evals/backend/configs/pr_subset.yaml

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
from pathlib import Path

# Add the evals/ directory to sys.path so `from runner.X import Y` resolves.
sys.path.insert(0, str(Path(__file__).parent))

from runner.eval_runner import run_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an eval suite.")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to a YAML eval config (e.g. evals/backend/configs/pr_subset.yaml)",
    )
    args = parser.parse_args()

    print(f"Running eval suite from config: {args.config}\n")

    try:
        summary = run_eval(args.config)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # Pretty-print the summary so it appears in the CI log
    print(json.dumps(summary, indent=2))

    status = "PASSED" if summary["suite_pass"] else "FAILED"
    print(
        f"\nSuite {status} — "
        f"pass_rate={summary['pass_rate']:.1%}  "
        f"avg_score={summary['avg_score']:.2f}  "
        f"schema_errors={summary['schema_error_rate']:.1%}"
    )

    if not summary["suite_pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
