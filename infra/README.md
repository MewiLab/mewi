# `infra/` — Terraform for Mewi's cloud

The AWS infrastructure for the **post-session report pipeline** (ADR-030 /
ADR-031 / ADR-032). Root config wires three child modules — `s3/` (buckets),
`sqs/` (the first-hop processing queue), and `aws-lambda/` (the report Lambdas)
— and the report runs entirely out-of-band from FastAPI: each finished game
session becomes two stored reports per user.

The pipeline is **two chains**:

- **First hop (ADR-032 — wired in Terraform/Python):** FastAPI stores the raw
  session in S3 and sends a compact SQS job; an event-source mapping runs
  `attachment-report`, which loads the raw sessions back from S3.
- **Second hop (ADR-031 — wired):** `attachment-report` writes `attachment.json`,
  whose S3 `ObjectCreated` event auto-invokes `recommendation-report`.

## How it works

```mermaid
flowchart TD
    UNITY["Unity — game session ends"]
    FASTAPI["FastAPI — validate · auth · enqueue<br/>(no scoring, no secrets)"]

    subgraph HOP1["First hop — ADR-032"]
        RAW["S3 raw/{user_id}/{session_id}.json"]
        SQS["SQS report-processing queue"]
        DLQ["SQS dead-letter queue"]
    end

    subgraph WIRED["Wired in this Terraform (ADR-031)"]
        ATTL["Lambda: attachment-report (report #1)"]
        ATT["S3 results/{user_id}/attachment.json"]
        RECL["Lambda: recommendation-report (report #2)<br/>reuses attachment output"]
        REC["S3 results/{user_id}/recommendation.json"]
        RF["RAGFlow knowledge base"]
        SECRETS["Lambda env secrets<br/>ANTHROPIC_API_KEY · RAGFLOW_*"]
    end

    ASTRO["Astro report site — two pages"]

    UNITY -->|HTTP POST /report/session| FASTAPI
    FASTAPI -->|put raw session| RAW
    FASTAPI -->|send job pointer| SQS
    SQS -->|event source mapping| ATTL
    SQS -.->|after max receives| DLQ
    ATTL -->|load raw sessions| RAW

    ATTL -->|put_object| ATT
    ATT -->|S3 ObjectCreated event| RECL
    RECL -->|put_object| REC
    RF -.->|retrieve| ATTL
    RF -.->|retrieve| RECL
    SECRETS -.->|env| ATTL
    SECRETS -.->|env| RECL
    ATT -->|presigned URL / API| ASTRO
    REC -->|presigned URL / API| ASTRO
```

Solid edges are wired in Terraform/Python. The `RF`/`SECRETS` dotted edges are
config (retrieval + env), not missing wiring. What is wired today: the raw bucket,
SQS queue/DLQ, SQS event-source mapping to `attachment-report`, report-results
bucket, Lambda S3/SQS IAM, Lambda env, and the second-hop
`attachment.json → recommendation-report` notification (suffix-filtered so report
#2's own output can't retrigger the chain). FastAPI's AWS sender role is optional
because the backend host is not defined here: set
`TF_VAR_backend_report_sender_role_name` if Terraform should attach its
write/send policy. Processing secrets live **only** in the Lambda env — FastAPI
never needs them.

## Layout

```
infra/
  deploy.sh            # one command: load secrets, vendor deps, init/plan/apply
  secrets.env.example  # copy to secrets.env (gitignored), fill in your keys
  main.tf              # root: wires the s3 + aws-lambda modules together
  variables.tf         # the inputs you configure (region, project, secrets, model)
  provider.tf          # AWS provider + region
  backend.tf           # remote Terraform state (S3, created manually)
  s3/                  # data buckets, incl. report raw + results buckets
  sqs/                 # report-processing queue + DLQ
  aws-lambda/          # the report Lambdas + their registry (see its README)
```

## Use

```bash
cd infra
cp secrets.env.example secrets.env   # first time only — then fill in your keys
./deploy.sh                          # loads secrets, vendors Lambda deps, plan + apply
```

`deploy.sh` sources `secrets.env` (gitignored), so secrets are never committed.
It also `pip install`s each Lambda's deps into its folder before `apply` (the
`archive_file` zips the dir as-is). After apply, copy the Terraform outputs into
the backend runtime:

```bash
MEWI_REPORT_PROCESSING_MODE=sqs
MEWI_REPORT_RAW_BUCKET=<terraform output report_raw_bucket>
MEWI_REPORT_SQS_QUEUE_URL=<terraform output report_processing_queue_url>
AWS_REGION=ap-southeast-1
```

See [`aws-lambda/README.md`](aws-lambda/README.md) for the report-Lambda details
and how to activate `recommendation-report`.
