# WHERE does Terraform store its state file?
#
# Why this exists:
#   Terraform needs to remember what it created last time.
#   Without this, every `terraform apply` thinks nothing exists
#   and tries to create everything again.
#
#   Storing state in S3 means:
#   - GitHub Actions (a fresh machine each run) can still find it
#   - Your teammate can run Terraform and see the same state
#
# NOTE: This bucket must be created MANUALLY first (or by a
#       bootstrap script) because Terraform can't create the
#       bucket it needs to store its own state — chicken-and-egg.


terraform {
  backend "s3" {
    bucket  = "mewi-tf-state-sg"
    key     = "terraform/state"
    region  = "ap-southeast-1"
    encrypt = true
  }
}
