# ── The Lambda registry ───────────────────────────────────────────────────────
#
# WHAT this file is:
#   The single place that says "how many report Lambdas do I have, and what are
#   they called." Everything else in this directory is just the code each Lambda
#   ships. Add a Lambda by doing two things:
#
#     1. create  infra/aws-lambda/<domain>/  with a handler.py exposing `handler`
#        (copy the attachment-report/ layout: handler.py + a domain module +
#         skills/ + requirements.txt)
#     2. add  "<domain>"  to local.lambdas below
#
#   `terraform apply` then zips that directory and deploys one Lambda for it.
#
# This is a CHILD MODULE: infra/main.tf wires it in with a `module "aws_lambda"`
# block, so it inherits the AWS provider/region from the root. It declares its
# own inputs (variables) and resources here to stay self-contained.

# ── The roster ─────────────────────────────────────────────────────────────────
locals {
  # One entry per Lambda. The string is BOTH the directory name under
  # infra/aws-lambda/ AND the resource key / function suffix. Keep it kebab-case.
  #
  # recommendation-report is scaffolded but NOT implemented yet, so it is left
  # commented out — uncomment to deploy once recommendation.py is filled in.
  lambdas = [
    "attachment-report",
    # "recommendation-report",
  ]
}

# ── Inputs ─────────────────────────────────────────────────────────────────────
variable "project_name" {
  description = "Project name, used as prefix for resource names (matches the root)."
  type        = string
  default     = "mewi"
}

variable "anthropic_api_key" {
  description = "ANTHROPIC_API_KEY passed to the report Lambdas (the agent runs need it)."
  type        = string
  sensitive   = true
  default     = ""
}

# ── Packaging ──────────────────────────────────────────────────────────────────
# Zip each domain directory into a deployable artifact. Whatever is in the
# directory at apply time gets shipped, so install requirements.txt INTO the
# directory (pip install -r requirements.txt -t <domain>/) or build the zip in
# CI before running Terraform.
data "archive_file" "lambda" {
  for_each    = toset(local.lambdas)
  type        = "zip"
  source_dir  = "${path.module}/${each.key}"
  output_path = "${path.module}/.build/${each.key}.zip"
}

# ── Execution role ─────────────────────────────────────────────────────────────
# One role shared by all report Lambdas. Minimal for now: just CloudWatch Logs.
# Add S3 / SQS / EventBridge permissions here when the hand-off is wired up.
data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "report_lambda" {
  name               = "${var.project_name}-report-lambda"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy_attachment" "report_lambda_logs" {
  role       = aws_iam_role.report_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# S3 read/write for the report-results bucket: attachment-report writes
# attachment.json; recommendation-report reads it and writes recommendation.json.
# Scoped to objects under this one bucket. Skipped when no bucket is wired.
#
# count gates on results_bucket (the NAME), not results_bucket_arn: the bucket
# name is config-known at plan time, while .arn is a computed attribute that can
# be unknown until apply — and count must be known at plan time.
data "aws_iam_policy_document" "report_lambda_s3" {
  count = var.results_bucket != "" ? 1 : 0
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${var.results_bucket_arn}/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [var.results_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["results/*", "config/*"]
    }
  }
}

resource "aws_iam_role_policy" "report_lambda_s3" {
  count  = var.results_bucket != "" ? 1 : 0
  name   = "${var.project_name}-report-lambda-s3"
  role   = aws_iam_role.report_lambda.id
  policy = data.aws_iam_policy_document.report_lambda_s3[0].json
}

# Raw-session S3 read/list for attachment-report's SQS jobs. The queue message is
# only a job pointer, so the Lambda lists raw/{user_id}/ and reads each session.
data "aws_iam_policy_document" "report_lambda_raw_s3" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${var.raw_bucket_arn}/raw/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [var.raw_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["raw/*"]
    }
  }
}

resource "aws_iam_role_policy" "report_lambda_raw_s3" {
  name   = "${var.project_name}-report-lambda-raw-s3"
  role   = aws_iam_role.report_lambda.id
  policy = data.aws_iam_policy_document.report_lambda_raw_s3.json
}

# SQS consume permissions for the event-source mapping that invokes
# attachment-report.
data "aws_iam_policy_document" "report_lambda_sqs" {
  statement {
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = [var.report_processing_queue_arn]
  }
}

resource "aws_iam_role_policy" "report_lambda_sqs" {
  name   = "${var.project_name}-report-lambda-sqs"
  role   = aws_iam_role.report_lambda.id
  policy = data.aws_iam_policy_document.report_lambda_sqs.json
}

# ── The Lambdas ────────────────────────────────────────────────────────────────
resource "aws_lambda_function" "report" {
  for_each = toset(local.lambdas)

  function_name = "${var.project_name}-${each.key}"
  role          = aws_iam_role.report_lambda.arn

  filename         = data.archive_file.lambda[each.key].output_path
  source_code_hash = data.archive_file.lambda[each.key].output_base64sha256

  handler = "handler.handler"
  runtime = "python3.12"

  # The agent run is LLM-bound, so give it room and time.
  timeout     = 300
  memory_size = 1024

  environment {
    variables = {
      ANTHROPIC_API_KEY = var.anthropic_api_key
    }
  }
}

# ── Outputs ────────────────────────────────────────────────────────────────────
output "lambda_function_names" {
  description = "Deployed report Lambda function names, keyed by domain."
  value       = { for k, fn in aws_lambda_function.report : k => fn.function_name }
}

output "lambda_function_arns" {
  description = "Deployed report Lambda ARNs, keyed by domain."
  value       = { for k, fn in aws_lambda_function.report : k => fn.arn }
}
