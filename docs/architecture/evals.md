## Evals System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                               GitHub (Control Plane)                        │
│                                                                             │
│  Developer PR/Push                                                         │
│      │                                                                      │
│      ▼                                                                      │
│  GitHub Repo (code + small datasets + rubrics + configs)                    │
│      │                                                                      │
│      ▼                                                                      │
│  GitHub Actions Workflow (PR subset gate)                                   │
│   - uv sync                                                                  │
│   - run subset evals                                                         │
│   - produce summary/results/report                                           │
│   - upload CI artifacts                                                      │
│   - (optional) trigger AWS full eval                                         │
│      │                                                                      │
│      ├──────────────► GitHub Status Check (pass/fail)                        │
│      └──────────────► PR Comment (metrics + artifact links)                  │
│                                                                             │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │  OIDC AssumeRole (no long-lived AWS keys)
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                AWS (Data Plane)                              │
│                                                                             │
│  S3 Bucket: agent-evals-*                                                    │
│   - datasets/ (full suites, versioned)                                       │
│   - rubrics/ (versioned)                                                     │
│   - configs/ (versioned)                                                     │
│   - runs/<run_id>/ (artifacts + metrics)                                     │
│                                                                             │
│  (Optional / later) SQS Queue: eval-jobs                                     │
│                                                                             │
│  (Full runs) ECS Fargate / AWS Batch                                         │
│   - pulls dataset/config/rubric from S3                                      │
│   - runs eval runner container                                               │
│   - writes artifacts back to S3                                              │
│   - logs to CloudWatch                                                      │
│                                                                             │
│  CloudWatch Logs + Metrics                                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```


## Github Action Flow
```
Developer opens PR
   │
   ▼
GitHub Actions: "Evals (PR subset)"
   │
   ├─ Checkout code
   ├─ Setup uv + Python 3.12
   ├─ uv sync --frozen
   ├─ Run: backend/evals/run_eval.py --config pr_subset.yaml
   │     ├─ Load dataset (repo small subset)
   │     ├─ Local checks (judge.py)
   │     ├─ LLM judge (openai_judge.py)  [optional; or mock for fork PRs]
   │     ├─ Aggregate metrics
   │     └─ Write artifacts: summary.json / results.jsonl / report.md
   │
   ├─ Upload GitHub artifact (evals-pr-subset)
   ├─ Set GitHub Status Check (pass/fail by thresholds)
   │
   └─ (Optional) Upload artifacts to S3 (runs/<run_id>/...) via OIDC
        └─ For long-term history & comparison
```


## Full Evaluation Flow
```
PR labeled "run-full-eval" OR nightly schedule
   │
   ▼
GitHub Actions (OIDC AssumeRole)
   │
   ▼
SQS Queue: eval-jobs
   │
   ▼
ECS Service Worker (polls SQS)
   │
   ├─ For each message:
   │    - run_id, suite, dataset_uri, rubric_uri, git_sha
   ├─ Run eval container
   ├─ Upload run artifacts to S3
   └─ Emit metrics/logs (CloudWatch)
```