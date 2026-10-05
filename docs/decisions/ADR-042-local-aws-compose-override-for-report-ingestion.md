# ADR-042: Local AWS Compose Override For Report Ingestion

- **Status:** Accepted
- **Date:** 2026-06-07
- **Scope:** Local development workflow for running `mewi-backend` in Docker
  while testing ADR-032's S3/SQS report handoff.
- **Builds on:** [ADR-024](ADR-024-backend-makefile-and-graph-db-workflow.md)
  for the backend Docker workflow,
  [ADR-031](ADR-031-report-end-to-end-workflow.md) for report result storage,
  and [ADR-032](ADR-032-sqs-first-hop-report-ingestion.md) for the SQS first
  hop.

## Context

The production report ingest path is:

```text
FastAPI /api/v1/report/session
  -> S3 raw session put_object
  -> SQS report-processing message
  -> attachment-report Lambda
  -> S3 results/{user_id}/attachment.json
```

When `mewi_agent_runtime` runs in Docker with:

```text
MEWI_REPORT_PROCESSING_MODE=sqs
MEWI_REPORT_RAW_BUCKET=mewi-report-raw-v0
MEWI_REPORT_SQS_QUEUE_URL=...
AWS_REGION=ap-southeast-1
```

the container also needs an AWS identity. The host may have
`~/.aws/credentials`, but the container cannot see that file by default. The
failure mode is:

```text
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```

This can look like a Lambda/SQS problem, but the report request has not reached
SQS yet. FastAPI fails while writing the raw session to S3.

The quick fix used during debugging was a Compose override with an absolute host
path such as `/Users/harris/.aws:/root/.aws:ro`. That file is useful locally but
must not be committed: it is machine-specific and points at private credential
material.

## Decision

Keep local AWS credential wiring in an ignored Compose override file and commit
only a sanitized example.

Tracked example:

```text
mewi-backend/docker-compose.aws.override.example.yml
```

Ignored local files:

```text
mewi-backend/docker-compose.aws.override.yml
mewi-backend/mewi-backend-aws.override.yml
```

The example mounts the caller's host AWS config into the current Docker image's
root home directory, read-only:

```yaml
services:
  mewi_agent_runtime:
    environment:
      AWS_PROFILE: ${AWS_PROFILE:-default}
      AWS_SDK_LOAD_CONFIG: "1"
    volumes:
      - ${HOME}/.aws:/root/.aws:ro
```

Run local S3/SQS report ingestion with:

```bash
cd mewi-backend
cp docker-compose.aws.override.example.yml docker-compose.aws.override.yml
docker compose -f docker-compose.yml -f docker-compose.aws.override.yml up -d mewi_agent_runtime
```

The backend `.env` still owns report-mode configuration:

```text
MEWI_REPORT_PROCESSING_MODE=sqs
MEWI_REPORT_RAW_BUCKET=mewi-report-raw-v0
MEWI_REPORT_SQS_QUEUE_URL=<terraform output report_processing_queue_url>
AWS_REGION=ap-southeast-1
AWS_DEFAULT_REGION=ap-southeast-1
```

The Compose override owns only local AWS credential visibility.

## Consequences

- Local Docker can test the real S3/SQS/Lambda handoff without copying AWS keys
  into `.env`.
- The mounted credentials are read-only and stay outside Git.
- The local override is developer-specific. If the Docker image stops running as
  root, the mount target must change from `/root/.aws` to that user's home.
- This is a local development convenience, not a production identity model.
  Production should use a task role, instance role, or similarly scoped runtime
  identity.
- A successful ingest should return:

```json
{
  "stored": true,
  "processing_queued": true,
  "storage_key": "raw/{user_id}/{session_id}.json"
}
```

If `processing_queued` is false, FastAPI is still in `noop` mode. If the request
returns a 500 with `NoCredentialsError`, the container cannot see a usable AWS
identity.
