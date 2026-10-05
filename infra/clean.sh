#!/usr/bin/env bash
#
# clean.sh — remove local Lambda build artifacts created by deploy.sh.
#
# Use this after a successful deploy when you want the working tree tidy again:
#
#     cd infra
#     ./clean.sh
#
# It removes generated zip files and vendored dependency files only. Source files
# such as handler.py, requirements.txt, skills/, and Terraform files are left
# alone.

set -euo pipefail

cd "$(dirname "$0")"

echo "==> removing Terraform archive_file output"
rm -rf aws-lambda/.build

echo "==> removing vendored Lambda dependencies"
for req in aws-lambda/*/requirements.txt; do
  [[ -e "$req" ]] || continue
  dir="$(dirname "$req")"
  marker="$dir/.deps-vendored"
  manifest="$dir/.deps-vendored-manifest"
  echo "    - $dir"
  if [[ -f "$manifest" ]]; then
    while IFS= read -r entry; do
      [[ -n "$entry" ]] || continue
      [[ "$entry" == /* || "$entry" == *".."* ]] && continue
      rm -rf "$dir/$entry"
    done < "$manifest"
  else
    # Fallback for deps installed before deploy.sh wrote a manifest.
    rm -rf \
      "$dir/bin" \
      "$dir"/*.dist-info \
      "$dir"/*.egg-info \
      "$dir"/*.pth \
      "$dir"/*-stubs \
      "$dir/annotated_types" \
      "$dir/anthropic" \
      "$dir/anyio" \
      "$dir/boto3" \
      "$dir/botocore" \
      "$dir/certifi" \
      "$dir/claude_agent_sdk" \
      "$dir/dateutil" \
      "$dir/distro" \
      "$dir/docstring_parser" \
      "$dir/h11" \
      "$dir/httpcore" \
      "$dir/httpx" \
      "$dir/idna" \
      "$dir/jiter" \
      "$dir/jmespath" \
      "$dir/pydantic" \
      "$dir/pydantic_core" \
      "$dir/s3transfer" \
      "$dir/sniffio" \
      "$dir/typing_extensions.py" \
      "$dir/typing_inspection" \
      "$dir/urllib3" \
      "$dir/websockets" \
      "$dir/yaml" \
      "$dir/zstandard"
  fi
  rm -f "$marker" "$manifest"
done

echo "==> removing Python caches"
find aws-lambda -type d -name "__pycache__" -prune -exec rm -rf {} +
find aws-lambda -type f -name "*.pyc" -delete

echo "==> done"
