"""Core eval orchestrator.

Responsibility:
  1. Load config (YAML) → dataset (JSONL) → rubric (Markdown)
  2. For each case, pick the right judge (local | LLM | mock)
  3. Aggregate results into pass_rate / avg_score / schema_error_rate
  4. Write three output files: summary.json, results.jsonl, report.md
  5. Return the summary dict so the CLI can exit with the right code

Why split judge selection here rather than in run_eval.py?
  The runner owns the per-case loop so it can handle retries and partial
  failures without the CLI needing to know the details.
"""

import json
import os
import uuid
from pathlib import Path

import yaml


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_repo_root(start: Path) -> Path:
    """Walk up from `start` until we find a .git directory (= repo root)."""
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    # Fallback: caller's working directory
    return Path.cwd()


def _load_config(config_path: Path) -> dict:
    with config_path.open() as fh:
        return yaml.safe_load(fh)


def _load_dataset(dataset_path: Path) -> list[dict]:
    cases = []
    with dataset_path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _load_rubric(rubric_path: Path) -> str:
    return rubric_path.read_text()


def _mock_judge(case: dict) -> dict:
    """Always-pass stub used when OPENAI_API_KEY is absent and mode is 'mock'."""
    return {
        "pass": True,
        "score": 5,
        "reasons": ["mock judge — no API call made"],
        "parsed_json": None,
    }


def _judge_case(case: dict, mode: str, rubric_text: str, openai_cfg: dict) -> dict:
    """Route a single case to the appropriate judge."""
    has_api_key = bool(os.environ.get("OPENAI_API_KEY"))

    if mode == "openai" and has_api_key:
        from runner.openai_judge import llm_judge
        return llm_judge(
            case,
            rubric_text,
            model=openai_cfg.get("model", "gpt-4o-mini"),
            temperature=openai_cfg.get("temperature", 0),
            max_tokens=openai_cfg.get("max_output_tokens", 300),
        )

    if mode == "openai" and not has_api_key:
        # Graceful degradation: fall back to local checks in CI without a key
        # (e.g. fork PRs that can't access secrets)
        from runner.judge import local_judge
        return local_judge(case)

    if mode == "local":
        from runner.judge import local_judge
        return local_judge(case)

    # mode == "mock" (or anything else)
    return _mock_judge(case)


def _write_outputs(output_dir: Path, summary: dict, results: list[dict], config: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # summary.json ─ machine-readable overview
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # results.jsonl ─ one JSON object per line, one line per case
    with (output_dir / "results.jsonl").open("w") as fh:
        for r in results:
            fh.write(json.dumps(r) + "\n")

    # report.md ─ human-readable table for GitHub PR comment / artifact viewer
    thresholds = config.get("thresholds", {})
    status_icon = "✅ PASS" if summary["suite_pass"] else "❌ FAIL"
    lines = [
        f"# Eval Report: `{summary['suite']}`",
        "",
        f"**Result: {status_icon}** &nbsp; run `{summary['run_id']}`",
        "",
        "| Metric | Value | Threshold |",
        "|--------|------:|----------:|",
        f"| Pass rate | {summary['pass_rate']:.1%} | ≥ {thresholds.get('pass_rate_min', '—')} |",
        f"| Avg score | {summary['avg_score']:.2f} | ≥ {thresholds.get('avg_score_min', '—')} |",
        f"| Schema error rate | {summary['schema_error_rate']:.1%} | ≤ {thresholds.get('schema_error_rate_max', '—')} |",
        "",
        "## Case Results",
        "",
    ]
    for r in results:
        icon = "✅" if r["pass"] else "❌"
        lines.append(f"### {icon} `{r['id']}` — score {r['score']}/5")
        for reason in r.get("reasons", []):
            lines.append(f"- {reason}")
        lines.append("")

    (output_dir / "report.md").write_text("\n".join(lines))


# ── Public entry point ─────────────────────────────────────────────────────────

def run_eval(config_path_str: str) -> dict:
    """Run a full eval suite defined by a YAML config file.

    Paths inside the config are resolved relative to the repo root so they
    work whether you invoke the script from `backend/` (CI) or the repo root.

    Returns the summary dict. Raises on hard errors.
    """
    config_path = Path(config_path_str)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path

    config = _load_config(config_path)
    repo_root = _find_repo_root(config_path)

    # Resolve dataset / rubric / output paths relative to repo root
    dataset_path = repo_root / config["dataset"]["path"]
    rubric_path = repo_root / config["rubric"]["path"]
    output_dir = repo_root / config["output"]["dir"]

    cases = _load_dataset(dataset_path)
    rubric_text = _load_rubric(rubric_path)

    runner_mode = config["runner"]["mode"]
    openai_cfg = config.get("openai", {})

    # ── Per-case judging ───────────────────────────────────────────────────
    results: list[dict] = []
    for case in cases:
        verdict = _judge_case(case, runner_mode, rubric_text, openai_cfg)
        results.append({"id": case["id"], **verdict})

    # ── Aggregate metrics ──────────────────────────────────────────────────
    total = len(results)
    num_passed = sum(1 for r in results if r["pass"])
    pass_rate = num_passed / total if total else 0.0
    avg_score = sum(r["score"] for r in results) / total if total else 0.0

    # Schema errors: cases where JSON was required but couldn't be parsed
    schema_errors = sum(
        1 for r in results if r["score"] == 0 and r["parsed_json"] is None
    )
    schema_error_rate = schema_errors / total if total else 0.0

    thresholds = config.get("thresholds", {})
    suite_pass = (
        pass_rate >= thresholds.get("pass_rate_min", 0.0)
        and avg_score >= thresholds.get("avg_score_min", 0.0)
        and schema_error_rate <= thresholds.get("schema_error_rate_max", 1.0)
    )

    summary = {
        "suite": config["suite"],
        "run_id": str(uuid.uuid4())[:8],
        "total": total,
        "passed": num_passed,
        "pass_rate": round(pass_rate, 4),
        "avg_score": round(avg_score, 4),
        "schema_error_rate": round(schema_error_rate, 4),
        "suite_pass": suite_pass,
        "thresholds": thresholds,
    }

    _write_outputs(output_dir, summary, results, config)
    return summary
