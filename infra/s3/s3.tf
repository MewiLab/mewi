# ── S3 buckets ─────────────────────────────────────────────────────────────────
#
# WHAT this module creates:
#   The project's data buckets. Today: the eval dataset + eval results buckets.
#   Add a bucket here and it stays grouped with the rest of the storage.
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

# ── Dataset bucket (already exists in AWS, will be imported) ───
resource "aws_s3_bucket" "eval_dataset" {
  bucket = "${var.project_name}-eval-dataset-v0"

  # force_destroy = true lets Terraform delete the bucket even if
  # it has files in it. Useful for dev. Remove this in production
  # to prevent accidental data loss.
  force_destroy = true
}

# Block all public access
# Why: S3 buckets are private by default, but this EXPLICITLY
# locks it down. Without this, a misconfigured bucket policy
# could accidentally expose your eval results to the internet.
resource "aws_s3_bucket_public_access_block" "eval_dataset" {
  bucket = aws_s3_bucket.eval_dataset.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# ── Results bucket (Terraform will create this) ────────────────
resource "aws_s3_bucket" "eval_results" {
  bucket        = "${var.project_name}-eval-result-v0"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "eval_results" {
  bucket = aws_s3_bucket.eval_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# ── Outputs ────────────────────────────────────────────────────────────────────
output "eval_dataset_bucket" {
  description = "Name of the eval dataset bucket."
  value       = aws_s3_bucket.eval_dataset.bucket
}

output "eval_results_bucket" {
  description = "Name of the eval results bucket."
  value       = aws_s3_bucket.eval_results.bucket
}
