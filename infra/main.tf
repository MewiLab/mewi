# ── Dataset bucket (already exists in AWS, will be imported) ───
# WHAT resources does Terraform create?
#
# This is the only file that talks to AWS and says "make this."
# Right now it's just one S3 bucket for eval results.

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
  bucket = aws_s3_bucket.eval_results.id

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