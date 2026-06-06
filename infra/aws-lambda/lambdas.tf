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
  # Two report products per user (ADR-031): attachment-report (report #1) and
  # recommendation-report (report #2, which REUSES attachment's output via
  # results/{user_id}/attachment.json in S3). recommendation-report's core is
  # still a scaffold (recommendation.py raises NotImplementedError), so it is
  # left commented out — uncomment to deploy once it is filled in.
  lambdas = [
    "attachment-report",
    # "recommendation-report",
  ]

  # The S3 trigger (attachment.json -> recommendation-report) only wires up when
  # recommendation-report is actually in the roster AND a results bucket exists.
  # So uncommenting the line above is all it takes to activate the chain.
  recommendation_enabled = contains(local.lambdas, "recommendation-report") && var.results_bucket != ""
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

variable "claude_model" {
  description = "Default Claude model for the report Lambdas (injected as CLAUDE_AGENT_MODEL)."
  type        = string
  default     = "claude-sonnet-4-6"
}

variable "ragflow_endpoint" {
  description = "RAGFlow base URL for evidence retrieval (ADR-031). Empty = retrieval disabled."
  type        = string
  default     = ""
}

variable "ragflow_api_key" {
  description = "RAGFlow API key passed to the report Lambdas."
  type        = string
  sensitive   = true
  default     = ""
}

variable "results_bucket" {
  description = "Report results bucket name (results/{user_id}/*.json). Empty = S3 read/write + the recommendation trigger are skipped."
  type        = string
  default     = ""
}

variable "results_bucket_arn" {
  description = "ARN of the report results bucket (for Lambda S3 IAM + the S3 notification source)."
  type        = string
  default     = ""
}

variable "raw_bucket" {
  description = "Report raw-session bucket name (raw/{user_id}/{session_id}.json) for attachment-report SQS jobs."
  type        = string
  default     = ""
}

variable "raw_bucket_arn" {
  description = "ARN of the report raw-session bucket for attachment-report S3 read/list IAM."
  type        = string
  default     = ""
}

variable "report_processing_queue_arn" {
  description = "ARN of the SQS queue that triggers attachment-report."
  type        = string
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

  # Secrets live ONLY here, in the Lambda env — never in FastAPI. The Anthropic
  # key drives the agent runs; the RAGFlow vars ground narrative wording. Empty
  # RAGFlow values mean retrieval is disabled and the Lambda falls back to
  # deterministic copy (ADR-031), so it is safe to leave them unset.
  environment {
    variables = {
      ANTHROPIC_API_KEY          = var.anthropic_api_key
      CLAUDE_AGENT_MODEL         = var.claude_model
      RAGFLOW_ENDPOINT           = var.ragflow_endpoint
      RAGFLOW_API_KEY            = var.ragflow_api_key
      MEWI_REPORT_RESULTS_BUCKET = var.results_bucket
      MEWI_REPORT_RAW_BUCKET     = var.raw_bucket
    }
  }
}

# ── The first hop: SQS → attachment-report ─────────────────────────────────────
# ADR-032: FastAPI writes raw sessions to S3, sends a compact SQS job, and this
# event-source mapping invokes attachment-report. Partial batch failure handling
# must be enabled on the mapping, not just returned by the handler.
resource "aws_lambda_event_source_mapping" "attachment_from_sqs" {
  event_source_arn = var.report_processing_queue_arn
  function_name    = aws_lambda_function.report["attachment-report"].arn
  # The handler supports batches, but one LLM-bound report can use most of the
  # 300s timeout. Process one job per invocation for predictable retries.
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]

  depends_on = [aws_iam_role_policy.report_lambda_sqs]
}

# ── The trigger: attachment.json in S3 → recommendation-report ──────────────────
# This is the missing link that makes report #2 run automatically after report #1
# is published. S3 emits an ObjectCreated event for the attachment.json key, which
# invokes recommendation-report. The suffix filter is deliberately "attachment.json"
# (not all .json) so recommendation's OWN output cannot retrigger the chain.
resource "aws_lambda_permission" "recommendation_from_s3" {
  count         = local.recommendation_enabled ? 1 : 0
  statement_id  = "AllowS3InvokeRecommendation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.report["recommendation-report"].function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.results_bucket_arn
}

resource "aws_s3_bucket_notification" "report_results" {
  count  = local.recommendation_enabled ? 1 : 0
  bucket = var.results_bucket

  lambda_function {
    lambda_function_arn = aws_lambda_function.report["recommendation-report"].arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "results/"
    filter_suffix       = "attachment.json"
  }

  # S3 rejects the notification config unless Lambda already trusts S3 to invoke.
  depends_on = [aws_lambda_permission.recommendation_from_s3]
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
