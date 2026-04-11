# WHAT values can change between environments?
#
# Why variables:
#   Hardcoding "ap-southeast-2" in 5 different files means
#   changing region requires editing 5 files.
#   A variable means you change it in ONE place.
#
# Why a separate file:
#   When someone new joins, they open variables.tf to see
#   "what do I need to configure?" — it's the control panel.

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "ap-southeast-2"
}

variable "project_name" {
  description = "Project name, used as prefix for resource names"
  type        = string
  default     = "mewi"
}
