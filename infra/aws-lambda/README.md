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
  attachment-report/             # ← one domain = one Lambda
    handler.py                   #   `handler.handler` — the Lambda entrypoint
    attachment_analysis.py       #   the domain logic (agent run + scoring)
    skills/
      attachment-analysis/
        SKILL.md                 #   the agent's operating method, bundled into the zip
    requirements.txt             #   deps to install into the dir before packaging
  recommendation-report/         # ← scaffold, same shape, not implemented yet
    handler.py
    recommendation.py            #   raises NotImplementedError until filled in
    skills/recommendation/SKILL.md
    requirements.txt
```

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

`attachment-report` is the Lambda copy of the agent path in
`mewi-backend/app/services/report/attachment_client.py` (+ its
`skills/attachment-analysis/SKILL.md`). Per ADR-014 / `report/trigger.py`, the
backend's `ProcessingTrigger` seam is meant to become an EventBridge/SQS →
Lambda hand-off; this directory is where that Lambda code lives. The backend
still keeps its in-process copy — these are a scaffold, not yet the live path.

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
