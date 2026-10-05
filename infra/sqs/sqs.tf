# ── SQS report-processing queue (ADR-032) ─────────────────────────────────────
#
# First hop:
#   FastAPI -> SQS report-processing queue -> attachment-report Lambda
#
# The message is only a compact job pointer. Raw sessions live in S3.

variable "project_name" {
  description = "Project name, used as prefix for resource names (matches the root)."
  type        = string
  default     = "mewi"
}

resource "aws_sqs_queue" "report_processing_dlq" {
  name                      = "${var.project_name}-report-processing-dlq"
  message_retention_seconds = 1209600 # 14 days, the SQS maximum.
}

resource "aws_sqs_queue" "report_processing" {
  name                       = "${var.project_name}-report-processing"
  visibility_timeout_seconds = 1800 # Lambda timeout is 300s; leave room for retries.

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.report_processing_dlq.arn
    maxReceiveCount     = 3
  })
}

output "report_processing_queue_url" {
  description = "URL of the report-processing queue for FastAPI MEWI_REPORT_SQS_QUEUE_URL."
  value       = aws_sqs_queue.report_processing.url
}

output "report_processing_queue_arn" {
  description = "ARN of the report-processing queue for Lambda event-source mapping and IAM."
  value       = aws_sqs_queue.report_processing.arn
}

output "report_processing_dlq_url" {
  description = "URL of the report-processing dead-letter queue for debugging failed jobs."
  value       = aws_sqs_queue.report_processing_dlq.url
}

output "report_processing_dlq_arn" {
  description = "ARN of the report-processing dead-letter queue."
  value       = aws_sqs_queue.report_processing_dlq.arn
}
