# `infra/aws-lambda` — report-pipeline Lambdas

One directory per Lambda. Each directory is a self-contained "domain": a
`handler.py` entrypoint, the python module that does the work, the agent
`skills/` it ships, and a `requirements.txt`. [`lambdas.tf`](lambdas.tf) is the
**registry** — the one file that says how many Lambdas exist and deploys them.

This is a Terraform child module, wired into the root in
[`../main.tf`](../main.tf) via `module "aws_lambda"`. It inherits the AWS
provider/region from the root.

## Layout

```
infra/aws-lambda/
  lambdas.tf                     # the registry: local.lambdas + the deploy resources
  README.md
  attachment-report/             # ← report #1: one domain = one Lambda
    handler.py                   #   `handler.handler` — the Lambda entrypoint
    attachment_analysis.py       #   the domain logic (agent run + scoring)
    report_processor.py          #   deterministic full page-shape builder
    _s3io.py                     #   tiny S3 result/raw-session helper (see chain below)
    skills/
      attachment-analysis/
        SKILL.md                 #   the agent's operating method, bundled into the zip
    requirements.txt             #   deps to install into the dir before packaging
  recommendation-report/         # ← report #2: reuses report #1's output; core scaffold
    handler.py                   #   resolves the attachment output (inline or from S3)
    recommendation.py            #   raises NotImplementedError until filled in
    _s3io.py                     #   copy of the S3 helper (self-contained zip)
    skills/recommendation/SKILL.md
    requirements.txt
```

## Two reports per user (the chain)

Each user gets **two report products**, one Lambda each. `recommendation-report`
does not re-derive from raw sessions — it **reuses `attachment-report`'s output**,
so attachment scoring stays the single source of truth (ADR-031):

```
FastAPI ─► raw S3 + SQS ─► attachment-report ─► results/{user_id}/attachment.json ─► page #1
                                      │
                                      └─ reused ─► recommendation-report ─► results/{user_id}/recommendation.json ─► page #2
```

The transport is S3, behind `_s3io.py`. Everything is gated on the
`MEWI_REPORT_RESULTS_BUCKET` env var: with it set, each handler writes its
`results/{user_id}/<product>.json` and `recommendation-report` reads
`attachment.json` when the event omits an inline `attachment` block. **Without**
the var (local runs / unit tests) the helper no-ops and the Lambdas behave as
plain `event in → JSON out`. The pages render the stored JSON only.

For the ADR-032 first hop, `attachment-report` also reads
`MEWI_REPORT_RAW_BUCKET` when invoked by SQS. SQS messages carry only
`user_id`/job metadata; the handler lists `raw/{user_id}/`, loads the full raw
session payloads from S3, builds the full website-ready
`ProcessedAttachmentReport`, and then writes `attachment.json`. The deterministic
page shape comes from `report_processor.py`; the Claude path only replaces the
nested `attachment_analysis` block when it succeeds.

> `_s3io.py` uses `boto3`, which ships in the AWS Lambda Python runtime, so it is
> intentionally **not** in `requirements.txt`. It is copied (not shared) into each
> domain because every directory is zipped self-contained. The `results/` S3
> bucket, raw-session bucket, `MEWI_REPORT_RESULTS_BUCKET` /
> `MEWI_REPORT_RAW_BUCKET` env, S3/SQS IAM, SQS event-source mapping, and the
> `attachment.json → recommendation-report` notification are all wired in
> Terraform. What is still missing for the full two-product chain: the
> `generate_recommendation` core, and uncommenting `recommendation-report` in the
> roster (the trigger is gated on its presence).

## The roster

The list of Lambdas lives in `local.lambdas` in [`lambdas.tf`](lambdas.tf). The
string is both the directory name and the function suffix (`mewi-<domain>`).
`recommendation-report` is present on disk but commented out of the roster until
it is implemented.

## Add a Lambda

1. Copy the `attachment-report/` layout into `infra/aws-lambda/<new-domain>/`.
2. Implement `handler.handler` + the domain module + `skills/`.
3. Add `"<new-domain>"` to `local.lambdas` in `lambdas.tf`.

## Where this came from

`attachment-report` is now the only report-generation owner. FastAPI stores raw
sessions and enqueues work; the deterministic page-shape builder
(`report_processor.py`) and the Claude path (`attachment_analysis.py` plus
`skills/attachment-analysis/SKILL.md`) live in this Lambda bundle. Per ADR-014 /
ADR-032 / `report/trigger.py`, the backend's `ProcessingTrigger` seam is only a
queue/no-op hand-off.

## Deploy

```bash
# 1. install each Lambda's deps INTO its directory (archive_file zips as-is)
pip install -r attachment-report/requirements.txt -t attachment-report/

# 2. from infra/ — the module is part of the root config
terraform init
terraform apply           # provide ANTHROPIC_API_KEY:
                          #   export TF_VAR_anthropic_api_key=sk-ant-...
```

> Packaging note: `archive_file` zips whatever is in the domain directory at
> apply time, so the `pip install -t .` step (or an equivalent CI build) must run
> first. `.build/` (the generated zips) and any vendored deps should be
> gitignored.
