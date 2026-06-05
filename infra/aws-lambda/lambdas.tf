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
