# ── Root configuration ─────────────────────────────────────────
# WHAT this file does:
#   It no longer declares resources directly. Each concern lives in
#   its own directory/module and is wired in here. This file is the
#   "table of contents" for the infrastructure.
#
#     s3/          → the project's data buckets
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

# ── Report Lambdas ─────────────────────────────────────────────
# Each Lambda is just a folder of code (see infra/aws-lambda/lambdas.tf
# for the roster). This block is the only wiring the root needs; the
# module inherits the AWS provider/region from this configuration.
module "aws_lambda" {
  source            = "./aws-lambda"
  project_name      = var.project_name
  anthropic_api_key = var.anthropic_api_key
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

# ── State migration ────────────────────────────────────────────
# The bucket resources moved from this root file into the s3/ module.
# These `moved` blocks tell Terraform the resources are the SAME ones,
# just at a new address — so `apply` migrates state in place instead of
# destroying and recreating the buckets. Safe to delete after one apply.
moved {
  from = aws_s3_bucket.eval_dataset
  to   = module.s3.aws_s3_bucket.eval_dataset
}

moved {
  from = aws_s3_bucket_public_access_block.eval_dataset
  to   = module.s3.aws_s3_bucket_public_access_block.eval_dataset
}

moved {
  from = aws_s3_bucket.eval_results
  to   = module.s3.aws_s3_bucket.eval_results
}

moved {
  from = aws_s3_bucket_public_access_block.eval_results
  to   = module.s3.aws_s3_bucket_public_access_block.eval_results
}
