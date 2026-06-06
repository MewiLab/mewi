# WHAT values can change between environments?
#
# Why variables:
#   Hardcoding "ap-southeast-1" in 5 different files means
#   changing region requires editing 5 files.
#   A variable means you change it in ONE place.
#
# Why a separate file:
#   When someone new joins, they open variables.tf to see
#   "what do I need to configure?" — it's the control panel.

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "ap-southeast-1"
}

variable "project_name" {
  description = "Project name, used as prefix for resource names"
  type        = string
  default     = "mewi"
}

variable "backend_report_sender_role_name" {
  description = "Optional IAM role name for the FastAPI runtime. When set, Terraform grants it raw-session S3 write/list and SQS SendMessage for ADR-032."
  type        = string
  default     = ""
}

variable "anthropic_api_key" {
  description = "ANTHROPIC_API_KEY for the report Lambdas (passed into the aws-lambda module). Set via TF_VAR_anthropic_api_key or a tfvars file — never commit it."
  type        = string
  sensitive   = true
  default     = ""
}

# Project-wide default Claude model for the report Lambdas. Injected as the
# CLAUDE_AGENT_MODEL env var — the global default in each Lambda's resolution
# chain (event["model"] > MEWI_REPORT_ATTACHMENT_MODEL > CLAUDE_AGENT_MODEL > SDK
# default). Not a secret, so it is fine to keep in config / commit.
variable "claude_model" {
  description = "Default Claude model for the report Lambdas (CLAUDE_AGENT_MODEL)."
  type        = string
  default     = "claude-sonnet-4-6"
}

# RAGFlow grounding for the narrative/report Lambdas (ADR-031). Like the
# Anthropic key, these live ONLY in the Lambda env — FastAPI never needs them,
# because narrative generation runs out-of-band in the Lambda, not the request
# path. Set via TF_VAR_ragflow_endpoint / TF_VAR_ragflow_api_key — never commit.
variable "ragflow_endpoint" {
  description = "RAGFlow base URL for evidence retrieval (e.g. https://ragflow.example.com). Empty = retrieval disabled; the Lambda falls back to deterministic copy."
  type        = string
  default     = ""
}

variable "ragflow_api_key" {
  description = "RAGFlow API key for the report Lambdas."
  type        = string
  sensitive   = true
  default     = ""
}
