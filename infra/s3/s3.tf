# ── S3 buckets ─────────────────────────────────────────────────────────────────
#
# WHAT this module creates:
#   The project's report data buckets. Add a bucket here and it stays grouped
#   with the rest of the storage.
#
# This is a CHILD MODULE: infra/main.tf wires it in with a `module "s3"` block,
# so it inherits the AWS provider/region from the root.
#
# NOTE: this is NOT the Terraform *state* backend bucket (mewi-tf-state-sg). That
# one lives in infra/backend.tf at the root, is created manually, and stores
# Terraform's own state — it is intentionally separate from these data buckets.

variable "project_name" {
  description = "Project name, used as prefix for resource names (matches the root)."
  type        = string
  default     = "mewi"
}

# ── Report results bucket (ADR-031) ────────────────────────────
# Holds the two per-user report products written by the Lambdas:
#   results/{user_id}/attachment.json       (report #1)
#   results/{user_id}/recommendation.json   (report #2)
# attachment.json landing here is what triggers recommendation-report — the
# S3 event notification lives in the aws-lambda module (it owns that Lambda).
resource "aws_s3_bucket" "report_results" {
  bucket        = "${var.project_name}-report-results-v0"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "report_results" {
  bucket = aws_s3_bucket.report_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Report raw-session bucket (ADR-032) ───────────────────────
# Durable input store for first-hop processing. FastAPI writes full
# ReportSessionPayload JSON under:
#   raw/{user_id}/{session_id}.json
# attachment-report later lists raw/{user_id}/ and reads the objects when an SQS
# job arrives.
resource "aws_s3_bucket" "report_raw" {
  bucket        = "${var.project_name}-report-raw-v0"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "report_raw" {
  bucket = aws_s3_bucket.report_raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# ── Outputs ────────────────────────────────────────────────────────────────────
output "report_results_bucket" {
  description = "Name of the report results bucket (results/{user_id}/*.json)."
  value       = aws_s3_bucket.report_results.bucket
}

output "report_results_bucket_arn" {
  description = "ARN of the report results bucket (for Lambda IAM + S3 notification)."
  value       = aws_s3_bucket.report_results.arn
}

output "report_raw_bucket" {
  description = "Name of the report raw-session bucket (raw/{user_id}/{session_id}.json)."
  value       = aws_s3_bucket.report_raw.bucket
}

output "report_raw_bucket_arn" {
  description = "ARN of the report raw-session bucket (for FastAPI writes and Lambda reads)."
  value       = aws_s3_bucket.report_raw.arn
}
