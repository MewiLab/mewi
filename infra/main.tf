# ── Root configuration ─────────────────────────────────────────
# WHAT this file does:
#   It no longer declares resources directly. Each concern lives in
#   its own directory/module and is wired in here. This file is the
#   "table of contents" for the infrastructure.
#
#     s3/          → the project's data buckets
#     sqs/         → the report-processing first-hop queue
#     aws-lambda/  → the report-pipeline Lambdas (see its lambdas.tf)
#
# Root-only concerns stay at the root, NOT in a module:
#   backend.tf  → where Terraform stores its state (root-module only)
#   provider.tf → which cloud/region
#   variables.tf→ the inputs you configure

# ── S3 buckets ─────────────────────────────────────────────────
module "s3" {
  source       = "./s3"
  project_name = var.project_name
}

# ── SQS first-hop queue (ADR-032) ─────────────────────────────
module "sqs" {
  source       = "./sqs"
  project_name = var.project_name
}

# ── Report Lambdas ─────────────────────────────────────────────
# Each Lambda is just a folder of code (see infra/aws-lambda/lambdas.tf
# for the roster). This block is the only wiring the root needs; the
# module inherits the AWS provider/region from this configuration.
module "aws_lambda" {
  source            = "./aws-lambda"
  project_name      = var.project_name
  anthropic_api_key = var.anthropic_api_key
  claude_model      = var.claude_model
  ragflow_endpoint  = var.ragflow_endpoint
  ragflow_api_key   = var.ragflow_api_key

  # The report-results bucket lives in the s3 module; the Lambdas read/write it
  # and recommendation-report is triggered by attachment.json landing in it.
  results_bucket     = module.s3.report_results_bucket
  results_bucket_arn = module.s3.report_results_bucket_arn

  # ADR-032 first hop: SQS invokes attachment-report; the Lambda then reads raw
  # sessions from the raw bucket.
  raw_bucket                  = module.s3.report_raw_bucket
  raw_bucket_arn              = module.s3.report_raw_bucket_arn
  report_processing_queue_arn = module.sqs.report_processing_queue_arn
}

# ── Optional FastAPI sender IAM (ADR-032) ──────────────────────
# If the FastAPI runtime role is managed by this AWS account, set
# TF_VAR_backend_report_sender_role_name to grant only what the backend needs:
# write/list raw sessions, send report-processing jobs, and read finished
# report results. If FastAPI is hosted elsewhere, leave this empty and copy the
# same permissions to that runtime's AWS identity.
data "aws_iam_policy_document" "backend_report_sender" {
  count = var.backend_report_sender_role_name != "" ? 1 : 0

  statement {
    actions   = ["s3:PutObject"]
    resources = ["${module.s3.report_raw_bucket_arn}/raw/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [module.s3.report_raw_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["raw/*"]
    }
  }

  statement {
    actions   = ["sqs:SendMessage"]
    resources = [module.sqs.report_processing_queue_arn]
  }

  statement {
    actions   = ["s3:GetObject"]
    resources = ["${module.s3.report_results_bucket_arn}/results/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [module.s3.report_results_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["results/*"]
    }
  }
}

resource "aws_iam_role_policy" "backend_report_sender" {
  count  = var.backend_report_sender_role_name != "" ? 1 : 0
  name   = "${var.project_name}-backend-report-sender"
  role   = var.backend_report_sender_role_name
  policy = data.aws_iam_policy_document.backend_report_sender[0].json
}

# ── Runtime hand-off outputs ───────────────────────────────────
output "report_raw_bucket" {
  description = "FastAPI MEWI_REPORT_RAW_BUCKET value."
  value       = module.s3.report_raw_bucket
}

output "report_processing_queue_url" {
  description = "FastAPI MEWI_REPORT_SQS_QUEUE_URL value."
  value       = module.sqs.report_processing_queue_url
}

output "report_processing_queue_arn" {
  description = "Report-processing queue ARN."
  value       = module.sqs.report_processing_queue_arn
}

output "report_processing_dlq_url" {
  description = "Report-processing DLQ URL for debugging failed jobs."
  value       = module.sqs.report_processing_dlq_url
}
