#!/usr/bin/env bash
#
# deploy.sh — build + deploy the Mewi report Lambdas to AWS.
#
# This is the one command to memorize:
#
#     ./deploy.sh
#
# It does, in order:
#   1. loads your secrets (from infra/secrets.env — gitignored, never committed)
#   2. installs each Lambda's Python deps INTO its folder (Terraform zips the
#      folder as-is, so deps must be vendored in before apply)
#   3. terraform init -reconfigure  → plan → apply
#
# First-time setup:
#     cp secrets.env.example secrets.env     # then fill in your keys
#     ./deploy.sh
#
# Secrets are NEVER hardcoded here. They come from environment variables that
# Terraform reads automatically because of the TF_VAR_ prefix:
#     TF_VAR_anthropic_api_key   -> var.anthropic_api_key  (required)
#     TF_VAR_ragflow_endpoint    -> var.ragflow_endpoint   (optional)
#     TF_VAR_ragflow_api_key     -> var.ragflow_api_key    (optional)
#     TF_VAR_claude_model        -> var.claude_model       (optional; default claude-sonnet-4-6)

set -euo pipefail

# Always run from this script's directory (infra/), no matter where you call it.
cd "$(dirname "$0")"

# ── 1. Load secrets ─────────────────────────────────────────────────────────
# secrets.env is gitignored. If you already exported the TF_VARs in your shell,
# this just does nothing extra.
if [[ -f secrets.env ]]; then
  echo "==> loading secrets from secrets.env"
  set -a            # auto-export everything we source
  # shellcheck disable=SC1091
  source secrets.env
  set +a
fi

# Fail fast if the required key is missing (the agent runs can't work without it).
if [[ -z "${TF_VAR_anthropic_api_key:-}" ]]; then
  echo "ERROR: TF_VAR_anthropic_api_key is not set." >&2
  echo "       Copy secrets.env.example to secrets.env and fill it in, or export it." >&2
  exit 1
fi
if [[ "${TF_VAR_anthropic_api_key}" == "sk-ant-REPLACE_ME" || "${TF_VAR_anthropic_api_key}" == "sk-ant-..." ]]; then
  echo "ERROR: TF_VAR_anthropic_api_key still has the example placeholder value." >&2
  echo "       Put the real key in secrets.env, or export TF_VAR_anthropic_api_key." >&2
  exit 1
fi

# Prefer the same Python family as the Lambda runtime. Allow override if your
# machine names Python differently, e.g. PYTHON_FOR_LAMBDA=python3.12 ./deploy.sh.
PYTHON_FOR_LAMBDA="${PYTHON_FOR_LAMBDA:-python3.12}"
if ! command -v "$PYTHON_FOR_LAMBDA" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON_FOR_LAMBDA was not found." >&2
  echo "       Install Python 3.12 or run with PYTHON_FOR_LAMBDA=python3." >&2
  exit 1
fi

# ── 2. Vendor each deployed Lambda's Python deps into its folder ─────────────
# Terraform's archive_file zips the directory exactly as it is on disk, so the
# deps have to physically live next to the handler before we apply. Only install
# deps for Lambdas that are active in local.lambdas; scaffolded/commented folders
# can have experimental requirements without bloating this deploy.
echo "==> cleaning previous Lambda build artifacts"
./clean.sh

ACTIVE_LAMBDAS=()
while IFS= read -r lambda_name; do
  ACTIVE_LAMBDAS+=("$lambda_name")
done < <(
  awk '
    /lambdas[[:space:]]*=/ { in_list=1; next }
    in_list && /\]/ { in_list=0 }
    in_list {
      sub(/#.*/, "")
      if (match($0, /"[^"]+"/)) {
        value=substr($0, RSTART + 1, RLENGTH - 2)
        print value
      }
    }
  ' aws-lambda/lambdas.tf
)

if [[ ${#ACTIVE_LAMBDAS[@]} -eq 0 ]]; then
  echo "ERROR: no active Lambdas found in aws-lambda/lambdas.tf local.lambdas." >&2
  exit 1
fi

echo "==> installing Lambda dependencies"
for lambda_name in "${ACTIVE_LAMBDAS[@]}"; do
  req="aws-lambda/$lambda_name/requirements.txt"
  [[ -f "$req" ]] || {
    echo "ERROR: missing requirements.txt for active Lambda '$lambda_name'." >&2
    exit 1
  }
  dir="$(dirname "$req")"
  before="$(mktemp)"
  after="$(mktemp)"
  manifest="$dir/.deps-vendored-manifest"
  echo "    - $dir"
  find "$dir" -mindepth 1 -maxdepth 1 -exec basename {} \; | sort > "$before"
  "$PYTHON_FOR_LAMBDA" -m pip install -q -r "$req" -t "$dir"
  find "$dir" -mindepth 1 -maxdepth 1 -exec basename {} \; | sort > "$after"
  comm -13 "$before" "$after" | grep -v -E '^\.deps-vendored(-manifest)?$' > "$manifest" || true
  rm -f "$before" "$after"
  touch "$dir/.deps-vendored"
done

# ── 3. Terraform ────────────────────────────────────────────────────────────
# -reconfigure re-reads the backend config cleanly (safe to run every time).
echo "==> terraform init"
terraform init -reconfigure

echo "==> terraform plan"
terraform plan

# apply still prompts for confirmation by default — review the plan, then type yes.
echo "==> terraform apply"
terraform apply

# ── Post-deploy check (manual, do not paste real URLs into committed files) ───
# After a successful apply, verify the hand-off values with:
#
#     terraform output
#     terraform output -raw report_raw_bucket
#     echo
#     terraform output -raw report_processing_queue_url
#     echo
#
# Expected shape:
#     report_raw_bucket            -> mewi-report-raw-v0
#     report_processing_queue_url  -> https://sqs.<region>.amazonaws.com/<account>/<queue-name>
#     report_processing_dlq_url    -> https://sqs.<region>.amazonaws.com/<account>/<dlq-name>
#
# Then configure the FastAPI runtime (outside this script) with placeholders:
#     MEWI_REPORT_PROCESSING_MODE=sqs
#     MEWI_REPORT_RAW_BUCKET=<terraform output report_raw_bucket>
#     MEWI_REPORT_SQS_QUEUE_URL=<terraform output report_processing_queue_url>
#     AWS_REGION=ap-southeast-1
#
# In AWS Console, check region ap-southeast-1 for:
#     S3     -> report raw/results buckets
#     SQS    -> report-processing queue + DLQ
#     Lambda -> mewi-attachment-report with SQS trigger

echo "==> done. Check the AWS console (Lambda + S3) to confirm the resources."
